"""Regression tests: a background run always ends with status done or error, never half-finished."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import engine  # noqa: E402
import main  # noqa: E402
from tests.fakes import FakeAnthropic, FakePrices, make_modules, make_trade, rule_response  # noqa: E402

STREAK_RULE = rule_response(
    "Buys after 3+ down days",
    """
def rule(row):
    return "buy" if row["down_day_streak"] >= 3 else None
""",
)

TRADES = [
    make_trade("2026-01-01", "AAA", "buy", down_day_streak=3),
    make_trade("2026-01-02", "AAA", "buy", down_day_streak=4),
    make_trade("2026-01-03", "AAA", "buy", down_day_streak=3),
    make_trade("2026-01-04", "AAA", "sell", dist_from_ma20=0.1),
    make_trade("2026-01-05", "AAA", "sell", dist_from_ma20=0.1),
    make_trade("2026-01-06", "BBB", "sell"),
    make_trade("2026-01-07", "AAA", "buy", down_day_streak=3),
    make_trade("2026-02-01", "CCC", "sell", down_day_streak=3),
    make_trade("2026-02-02", "DDD", "buy", dist_from_ma20=0.1),
    make_trade("2026-02-03", "AAA", "sell", dist_from_ma20=0.2),
]


@pytest.fixture
def start_run(monkeypatch):
    """Run main.run_job synchronously against the real engine with fake parser/sandbox/Anthropic."""

    def _start(client):
        parser, features, sandbox = make_modules(TRADES)
        monkeypatch.setitem(sys.modules, "parser", parser)
        monkeypatch.setitem(sys.modules, "features", features)
        monkeypatch.setitem(sys.modules, "sandbox", sandbox)
        monkeypatch.setattr(engine, "_make_client", lambda: client)
        monkeypatch.setattr(engine, "fetch_close_after", FakePrices())
        main.runs.clear()
        main.run_job("run-1", main.RunRequest(trades_csv="date,symbol,side,qty,price\n"))
        return main.runs["run-1"]

    return _start


def test_normal_run_ends_done(start_run):
    record = start_run(FakeAnthropic([STREAK_RULE]))

    assert record["status"] == "done"
    assert record["run_id"] == "run-1"  # the id the client polls with
    assert len(record["hypotheses"]) == engine.MAX_ROUNDS
    assert any(h["status"] == "kept" for h in record["hypotheses"])
    assert {"baseline", "exceptions", "summary", "insights"} <= set(record)
    assert record["exceptions"]


def test_progress_updates_keep_run_id_and_status(monkeypatch):
    seen = []

    def fake_run_discovery(csv_path, on_progress):
        on_progress({"round": 1, "hypotheses": []})
        seen.append(dict(main.runs["run-1"]))
        return {"run_id": "engine-internal-id", "status": "done", "round": 1,
                "hypotheses": [], "baseline": {}, "exceptions": [], "summary": {}}

    monkeypatch.setattr(main.engine, "run_discovery", fake_run_discovery)
    main.runs.clear()
    main.run_job("run-1", main.RunRequest(trades_csv="x"))

    assert seen[0]["status"] == "running"
    assert seen[0]["run_id"] == "run-1"
    assert seen[0]["round"] == 1
    assert main.runs["run-1"]["status"] == "done"
    assert main.runs["run-1"]["run_id"] == "run-1"


def test_failing_round_sets_error_with_message(start_run):
    class ExplodingClient:
        def __init__(self):
            self.messages = type("M", (), {"create": staticmethod(self._create)})()

        def _create(self, **kwargs):
            raise RuntimeError("anthropic exploded")

    record = start_run(ExplodingClient())

    assert record["status"] == "error"
    assert "anthropic exploded" in record["message"]
    assert record["run_id"] == "run-1"


def test_failing_post_loop_step_sets_error_and_keeps_progress(start_run, monkeypatch):
    def boom(trades, kept):
        raise RuntimeError("exceptions step exploded")

    monkeypatch.setattr(engine, "_exceptions_and_summary", boom)
    record = start_run(FakeAnthropic([STREAK_RULE]))

    assert record["status"] == "error"
    assert "exceptions step exploded" in record["message"]
    assert len(record["hypotheses"]) == engine.MAX_ROUNDS  # progress made so far is kept


def test_exceptions_never_make_a_network_call(start_run, monkeypatch):
    import requests

    monkeypatch.setenv("BRIGHTDATA_API_KEY", "k")
    monkeypatch.setenv("BRIGHTDATA_ZONE", "z")
    monkeypatch.setattr(requests, "post", lambda *a, **k: pytest.fail("network call during a run"))

    record = start_run(FakeAnthropic([STREAK_RULE]))

    assert record["status"] == "done"
    assert all(e["context"] == ["No clear cause in the news"] for e in record["exceptions"])


def test_no_kept_rule_reports_no_exceptions(start_run):
    never_fires = rule_response("Never fires", "def rule(row):\n    return None")
    record = start_run(FakeAnthropic([never_fires]))

    assert record["status"] == "done"
    assert all(h["status"] == "rejected" for h in record["hypotheses"])
    assert record["exceptions"] == []
    assert "No rule" in record["summary"]["note"]


def test_whole_run_timeout_sets_error(monkeypatch):
    import threading
    import time

    monkeypatch.setattr(main, "RUN_TIMEOUT_SECONDS", 0.2)
    proceed = threading.Event()
    late_update = []

    def slow_run_discovery(csv_path, on_progress):
        proceed.wait(5)
        try:
            on_progress({"round": 1, "hypotheses": []})
        except main.RunTimedOut:
            late_update.append("stopped")
            raise
        return {"status": "done"}

    monkeypatch.setattr(main.engine, "run_discovery", slow_run_discovery)
    main.runs.clear()
    start = time.time()
    main.run_job("run-1", main.RunRequest(trades_csv="x"))

    assert time.time() - start < 3
    record = main.runs["run-1"]
    assert record["status"] == "error"
    assert "timed out" in record["message"]
    assert record["run_id"] == "run-1"

    proceed.set()  # the abandoned run must not overwrite the error record
    for _ in range(50):
        if late_update:
            break
        time.sleep(0.05)
    assert late_update == ["stopped"]
    assert main.runs["run-1"]["status"] == "error"


def test_anthropic_calls_have_a_30_second_timeout(start_run):
    client = FakeAnthropic([STREAK_RULE])
    start_run(client)

    assert len(client.calls) == engine.MAX_ROUNDS
    assert all(call["timeout"] == 30 for call in client.calls)
