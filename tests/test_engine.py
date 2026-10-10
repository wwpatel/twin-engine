import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import engine  # noqa: E402
from tests.fakes import FakeAnthropic, FakePrices, make_modules, make_trade, rule_response  # noqa: E402

STREAK_RULE = rule_response(
    "Buys after 3+ down days",
    """
def rule(row):
    return "buy" if row["down_day_streak"] >= 3 else None
""",
)
EXTENDED_RULE = rule_response(
    "Sells when price is more than 5% above its 20-day average",
    """
def rule(row):
    return "sell" if row["dist_from_ma20"] > 0.05 else None
""",
)
NEVER_FIRES_RULE = rule_response(
    "Buys right before earnings",
    """
def rule(row):
    return "buy" if row["days_to_next_earnings"] == -1 else None
""",
)
RAISING_RULE = rule_response(
    "Divides by zero",
    """
def rule(row):
    return 1 / 0
""",
)


def run(monkeypatch, trades, responses, closes=None):
    parser, features, sandbox = make_modules(trades)
    monkeypatch.setitem(sys.modules, "parser", parser)
    monkeypatch.setitem(sys.modules, "features", features)
    monkeypatch.setitem(sys.modules, "sandbox", sandbox)
    client = FakeAnthropic(responses)
    monkeypatch.setattr(engine, "_make_client", lambda: client)
    monkeypatch.setattr(engine, "fetch_close_after", FakePrices(closes))
    progress = []
    result = engine.run_discovery("trades.csv", progress.append)
    return result, client, progress, sandbox


def test_no_holdout_row_reaches_prompt(monkeypatch):
    discovery = [
        make_trade(f"2026-01-{d:02d}", "AAA", "buy" if d % 2 else "sell", ret_1d=-0.01 * d, dist_from_ma20=0.01 * d)
        for d in range(1, 15)
    ]
    holdout = [
        make_trade(f"2026-02-{d:02d}", "HOLDX", "sell", ret_1d=777.777, dist_from_ma20=-555.5)
        for d in range(1, 7)
    ]
    trades = holdout[::-1] + discovery[::-1]  # unsorted input: split must follow dates

    result, client, _, sandbox = run(monkeypatch, trades, [STREAK_RULE])

    prompts = client.prompts()
    assert len(client.calls) == engine.MAX_ROUNDS
    assert all(call["model"] == "claude-sonnet-4-6" for call in client.calls)
    for prompt in prompts:
        assert "HOLDX" not in prompt
        assert "777.777" not in prompt
        assert "555.5" not in prompt
        assert "2026-02" not in prompt
    assert "AAA" in prompts[1]
    assert "Trades: 14" in prompts[1]
    assert all("side" not in df.columns for _, df in sandbox.calls)
    assert result["status"] == "done"


def test_baseline_scored_on_holdout_only(monkeypatch):
    discovery = [make_trade(f"2026-01-{d:02d}", "AAA", "buy", ret_1d=-0.01) for d in range(1, 8)]
    holdout = [
        make_trade("2026-02-01", "AAA", "buy", ret_1d=-0.01),
        make_trade("2026-02-02", "AAA", "sell", ret_1d=-0.02),
        make_trade("2026-02-03", "AAA", "sell", ret_1d=0.03),
    ]

    result, *_ = run(monkeypatch, discovery + holdout, [NEVER_FIRES_RULE])

    assert result["baseline"]["holdout_match"] == pytest.approx(0.5)
    assert "ret_1d < 0" in result["baseline"]["text"]


def test_score_counts_only_fired_rows():
    match, coverage = engine.score(["buy", None, "sell", "buy"], ["buy", "sell", "buy", "buy"])
    assert match == pytest.approx(2 / 3)
    assert coverage == pytest.approx(0.75)
    assert engine.score([None, None], ["buy", "sell"]) == (None, 0.0)


def test_exception_selection(monkeypatch):
    trades = [
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
    closes = {
        ("AAA", "2026-01-01"): 102.0,
        ("AAA", "2026-02-03"): 99.0,
        ("BBB", "2026-01-06"): 90.0,
        ("CCC", "2026-02-01"): 105.0,
        ("DDD", "2026-02-02"): 110.0,
    }

    result, *_ = run(monkeypatch, trades, [STREAK_RULE, EXTENDED_RULE, NEVER_FIRES_RULE], closes)

    streak, extended = result["hypotheses"][:2]
    assert streak["status"] == extended["status"] == "kept"
    assert streak["discovery_match"] == extended["discovery_match"] == 1.0
    assert streak["holdout_match"] == 0.0
    assert extended["holdout_match"] == 0.5
    assert all(h["status"] == "rejected" for h in result["hypotheses"][2:])

    exceptions = result["exceptions"]
    assert [(e["date"], e["symbol"]) for e in exceptions] == [
        ("2026-01-06", "BBB"),
        ("2026-02-01", "CCC"),
        ("2026-02-02", "DDD"),
    ]
    assert all(e["broke_rule"] == "Buys after 3+ down days" for e in exceptions)
    assert all(e["context"] == [] for e in exceptions)
    assert [e["outcome_pct"] for e in exceptions] == [10.0, -5.0, 10.0]

    assert result["summary"] == {
        "followed_pct": pytest.approx(0.7),
        "return_when_followed": 1.5,
        "return_when_broken": 5.0,
    }


def test_raising_rule_is_rejected_and_loop_continues(monkeypatch):
    trades = [make_trade(f"2026-01-{d:02d}", "AAA", "buy", down_day_streak=3) for d in range(1, 11)]

    result, client, progress, _ = run(monkeypatch, trades, [RAISING_RULE, STREAK_RULE])

    first = result["hypotheses"][0]
    assert first["status"] == "rejected"
    assert "ZeroDivisionError" in first["reason"]
    assert len(client.calls) == engine.MAX_ROUNDS
    assert len(result["hypotheses"]) == engine.MAX_ROUNDS
    assert result["hypotheses"][1]["status"] == "kept"
    assert result["round"] == engine.MAX_ROUNDS
    assert [p["round"] for p in progress] == [1, 2, 3, 4, 5]
    assert [len(p["hypotheses"]) for p in progress] == [1, 2, 3, 4, 5]
    assert "Divides by zero" in client.prompts()[3]


def test_result_has_contract_shape(monkeypatch):
    trades = [make_trade(f"2026-01-{d:02d}", "AAA", "buy", down_day_streak=3) for d in range(1, 11)]

    result, *_ = run(monkeypatch, trades, [STREAK_RULE])

    assert set(result) == {"run_id", "status", "round", "hypotheses", "baseline", "exceptions", "summary"}
    assert set(result["hypotheses"][0]) == {"text", "status", "reason", "discovery_match", "holdout_match"}
    assert set(result["baseline"]) == {"text", "holdout_match"}
    assert set(result["summary"]) == {"followed_pct", "return_when_followed", "return_when_broken"}
