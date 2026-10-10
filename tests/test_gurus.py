import json
from unittest.mock import Mock

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import main
from main import app

client = TestClient(app)

RULE_R1 = 'def rule(row):\n    return "buy" if row.get("down_day_streak", 0) >= 3 else None'
RULE_R2 = 'def rule(row):\n    return "sell" if row.get("ret_5d", 0) > 0.05 else None'

GURU_INDEX = [
    {"id": "dip", "name": "Sample trader: Dip Buyer", "style": "dip", "bio": "Buys quality names after several consecutive down days and sells into the rebound."},
    {"id": "breakout", "name": "Sample trader: Breakout", "style": "breakout", "bio": "Buys stocks breaking out above their 20-day average on strong momentum and sells when momentum fades."},
    {"id": "defensive", "name": "Sample trader: Defensive", "style": "defensive", "bio": "Trims positions when the broad market weakens and only adds exposure on calm, rising days."},
]

DIP_INSIGHTS = [
    {"id": "rule_1", "title": "Buys after 3+ down days", "plain": "Buys after 3+ down days", "kind": "rule",
     "evidence": {"n_trades": None, "discovery_match": 0.8, "holdout_match": 0.64, "baseline_holdout_match": 0.4},
     "rule_code_id": "r1"},
    {"id": "rule_2", "title": "Sells into strength", "plain": "Sells into strength", "kind": "rule",
     "evidence": {"n_trades": None, "discovery_match": 0.7, "holdout_match": 0.71, "baseline_holdout_match": 0.4},
     "rule_code_id": "r2"},
    {"id": "exception_1", "title": "Exceptions in NVDA", "plain": "The trader broke their rules in 2 trades of NVDA.", "kind": "exception_pattern",
     "evidence": {"n_trades": 2, "discovery_match": None, "holdout_match": None, "baseline_holdout_match": 0.4},
     "rule_code_id": None},
]

DIP_PUBLIC = {
    "guru_id": "dip",
    "status": "done",
    "round": 5,
    "hypotheses": [
        {"text": "Buys after 3+ down days", "status": "kept", "reason": "Matched", "discovery_match": 0.8, "holdout_match": 0.64},
        {"text": "Sells into strength", "status": "kept", "reason": "Matched", "discovery_match": 0.7, "holdout_match": 0.71},
        {"text": "Buys on Mondays", "status": "rejected", "reason": "Weak", "discovery_match": 0.4, "holdout_match": None},
    ],
    "baseline": {"text": "Buys after any down day", "holdout_match": 0.38},
    "exceptions": [{"date": "2026-03-14", "symbol": "NVDA", "side": "buy", "broke_rule": "Buys after 3+ down days", "context": [], "outcome_pct": 4.2}],
    "summary": {"followed_pct": 0.76, "return_when_followed": 1.8, "return_when_broken": -0.9},
    "insights": DIP_INSIGHTS,
}


@pytest.fixture
def gurus_dir(tmp_path, monkeypatch):
    (tmp_path / "index.json").write_text(json.dumps(GURU_INDEX))
    (tmp_path / "dip.json").write_text(json.dumps(DIP_PUBLIC))
    (tmp_path / "dip.rules.json").write_text(json.dumps({"r1": RULE_R1, "r2": RULE_R2}))
    breakout = {**DIP_PUBLIC, "guru_id": "breakout", "hypotheses": [
        {"text": "Buys breakouts", "status": "rejected", "reason": "Weak", "discovery_match": 0.3, "holdout_match": None},
    ], "insights": []}
    (tmp_path / "breakout.json").write_text(json.dumps(breakout))
    # No files at all for defensive

    monkeypatch.setattr(main, "GURUS_DIR", str(tmp_path))
    main.load_gurus()
    yield tmp_path
    main.load_gurus(str(tmp_path / "empty"))


def test_list_gurus(gurus_dir):
    r = client.get("/gurus")
    assert r.status_code == 200
    data = r.json()
    assert [g["id"] for g in data] == ["dip", "breakout", "defensive"]
    for g in data:
        assert set(g.keys()) == {"id", "name", "style", "bio", "n_insights", "holdout_match"}
    assert data[0]["n_insights"] == 3
    assert data[0]["holdout_match"] == 0.71
    assert data[1]["n_insights"] == 0
    assert data[1]["holdout_match"] is None
    assert data[2]["n_insights"] == 0
    assert data[2]["holdout_match"] is None


def test_get_guru(gurus_dir):
    r = client.get("/gurus/dip")
    assert r.status_code == 200
    body = r.json()
    for key in ("hypotheses", "baseline", "exceptions", "summary", "insights"):
        assert key in body
    assert "rule_codes" not in body


def test_get_unknown_guru_404(gurus_dir):
    assert client.get("/gurus/defensive").status_code == 404
    assert client.get("/gurus/nope").status_code == 404


def test_missing_gurus_dir_returns_empty_list(tmp_path):
    main.load_gurus(str(tmp_path / "nope"))
    r = client.get("/gurus")
    assert r.status_code == 200
    assert r.json() == []


def test_malformed_index_tolerated(tmp_path):
    (tmp_path / "index.json").write_text("not json")
    main.load_gurus(str(tmp_path))
    r = client.get("/gurus")
    assert r.status_code == 200
    assert r.json() == []


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_no_endpoint_returns_rule_source(gurus_dir, monkeypatch):
    rule_source = RULE_R1
    monkeypatch.setitem(main.runs, "run_x", {
        "status": "done",
        "rule_codes": {"r1": rule_source},
        "insights": DIP_INSIGHTS,
    })
    monkeypatch.setattr("activate.sandbox.run_rule", Mock(return_value=["buy", None]))
    df = pd.DataFrame({
        "date": ["2026-01-01", "2026-01-02"],
        "symbol": ["NVDA", "AAPL"],
        "side": ["buy", "sell"],
        "down_day_streak": [3, 0],
    })
    monkeypatch.setattr("activate.features.build_features", Mock(return_value=df))
    monkeypatch.setattr("activate.pd.read_csv", Mock(return_value=df))
    monkeypatch.setattr("activate._outcome_pct", Mock(return_value=1.0))
    monkeypatch.setattr(main.news, "get_headlines", Mock(return_value=[{"title": "x", "source": "y", "published": "z"}]))
    main._news_calls.clear()

    responses = [
        client.get("/gurus"),
        client.get("/gurus/dip"),
        client.get("/runs/run_x"),
        client.post("/activate", json={"guru_id": "dip", "insight_id": "rule_1", "dataset": "follower_sample"}),
        client.post("/activate", json={"run_id": "run_x", "insight_id": "rule_1", "dataset": "follower_sample"}),
        client.get("/news", params={"symbol": "NVDA", "date": "2026-03-14"}),
        client.get("/health"),
    ]
    for r in responses:
        assert r.status_code == 200
        assert "def rule" not in r.text
        assert rule_source not in r.text
        assert RULE_R2 not in r.text
    assert "rule_codes" not in responses[2].json()
    assert "rule_codes" not in responses[1].json()
