import sys
from pathlib import Path
from unittest.mock import Mock, patch
import tempfile

import pytest
import pandas as pd
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import activate  # noqa: E402
import main  # noqa: E402

client = TestClient(main.app)


@pytest.fixture
def follower_sample_csv():
    """Create a temporary follower_sample.csv file for testing."""
    csv_content = """date,symbol,side,qty,price
2026-01-01,NVDA,buy,10,100.0
2026-01-02,AAPL,sell,10,150.0
2026-01-03,TSLA,buy,10,200.0
2026-01-04,GOOGL,sell,10,120.0
2026-01-05,MSFT,buy,10,300.0
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(csv_content)
        path = f.name
    yield path
    # Cleanup
    Path(path).unlink(missing_ok=True)


@pytest.fixture
def mock_run_store():
    """Create a mock run store with a run containing rule codes and insights."""
    return {
        "run123": {
            "rule_codes": {
                "r1": "def rule(row):\n    return \"buy\" if row.get(\"down_day_streak\", 0) >= 3 else None",
            },
            "insights": [
                {
                    "id": "rule_1",
                    "title": "Buys after 3+ down days",
                    "plain": "Buys after 3+ down days",
                    "kind": "rule",
                    "evidence": {
                        "n_trades": None,
                        "discovery_match": 0.8,
                        "holdout_match": 0.75,
                        "baseline_holdout_match": 0.4,
                    },
                    "rule_code_id": "r1",
                },
                {
                    "id": "exception_1",
                    "title": "Exceptions in NVDA",
                    "plain": "The trader broke their rules in 2 trades of NVDA.",
                    "kind": "exception_pattern",
                    "evidence": {
                        "n_trades": 2,
                        "discovery_match": None,
                        "holdout_match": None,
                        "baseline_holdout_match": 0.4,
                    },
                    "rule_code_id": None,
                },
            ],
        }
    }


def test_activate_success(follower_sample_csv, mock_run_store):
    """Test successful activation of a rule insight."""
    # Mock features.build_features to return a simple dataframe
    mock_df = pd.DataFrame({
        "date": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"],
        "symbol": ["NVDA", "AAPL", "TSLA", "GOOGL", "MSFT"],
        "side": ["buy", "sell", "buy", "sell", "buy"],
        "ret_1d": [-0.05, -0.03, -0.04, 0.01, -0.06],
        "down_day_streak": [3, 1, 4, 0, 5],
    })

    # Mock sandbox.run_rule to return actions
    mock_actions = ["buy", None, "buy", None, "buy"]

    with patch("activate.features.build_features", return_value=mock_df), \
         patch("activate.sandbox.run_rule", return_value=mock_actions), \
         patch("activate.pd.read_csv", return_value=mock_df), \
         patch("activate._outcome_pct", return_value=5.0):

        result = activate.activate(mock_run_store, "run123", "rule_1", "follower_sample")

        assert result["n_rule_applies"] == 3
        assert result["already_follows_pct"] == pytest.approx(1.0)  # All 3 match
        assert result["avg_outcome_when_followed"] == 5.0
        assert result["avg_outcome_when_not"] is None
        assert "Based on 3 of your 5 trades" in result["caveat"]


def test_activate_exception_pattern(follower_sample_csv, mock_run_store):
    """Test that activating an exception pattern insight returns 400."""
    with pytest.raises(ValueError, match="has no rule code"):
        activate.activate(mock_run_store, "run123", "exception_1", "follower_sample")


def test_activate_insight_not_found(follower_sample_csv, mock_run_store):
    """Test that activating a non-existent insight returns 400."""
    with pytest.raises(ValueError, match="Insight .* not found"):
        activate.activate(mock_run_store, "run123", "rule_999", "follower_sample")


def test_activate_run_not_found(follower_sample_csv, mock_run_store):
    """Test that activating from a non-existent run returns 400."""
    with pytest.raises(ValueError, match="Run .* not found"):
        activate.activate(mock_run_store, "run999", "rule_1", "follower_sample")


def test_activate_rule_code_not_found(follower_sample_csv, mock_run_store):
    """Test that activating when rule code is missing returns 400."""
    # Create a run with an insight that references a non-existent rule code
    mock_run_store["run123"]["insights"][0]["rule_code_id"] = "r999"

    with pytest.raises(ValueError, match="Rule code r999 not found"):
        activate.activate(mock_run_store, "run123", "rule_1", "follower_sample")


def test_activate_unknown_dataset(follower_sample_csv, mock_run_store):
    """Test that activating with an unknown dataset returns 400."""
    with pytest.raises(ValueError, match="Unknown dataset"):
        activate.activate(mock_run_store, "run123", "rule_1", "unknown_dataset")


def test_activate_partial_matches(follower_sample_csv, mock_run_store):
    """Test activation with partial matches between rule and follower."""
    mock_df = pd.DataFrame({
        "date": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"],
        "symbol": ["NVDA", "AAPL", "TSLA", "GOOGL", "MSFT"],
        "side": ["buy", "sell", "buy", "sell", "buy"],
        "ret_1d": [-0.05, -0.03, -0.04, 0.01, -0.06],
        "down_day_streak": [3, 1, 4, 0, 5],
    })

    # Rule fires on 3 trades, but only matches 2
    mock_actions = ["buy", None, "sell", None, "buy"]  # TSLA mismatch (rule says sell, actual is buy)

    with patch("activate.features.build_features", return_value=mock_df), \
         patch("activate.sandbox.run_rule", return_value=mock_actions), \
         patch("activate.pd.read_csv", return_value=mock_df), \
         patch("activate._outcome_pct", return_value=5.0):

        result = activate.activate(mock_run_store, "run123", "rule_1", "follower_sample")

        assert result["n_rule_applies"] == 3
        assert result["already_follows_pct"] == 0.6667  # 2 out of 3 match, rounded to 4 decimal places
        assert result["avg_outcome_when_followed"] == 5.0
        assert result["avg_outcome_when_not"] == 5.0


def test_activate_no_rule_applies(follower_sample_csv, mock_run_store):
    """Test activation when rule never fires."""
    mock_df = pd.DataFrame({
        "date": ["2026-01-01", "2026-01-02", "2026-01-03"],
        "symbol": ["NVDA", "AAPL", "TSLA"],
        "side": ["buy", "sell", "buy"],
        "ret_1d": [0.01, 0.02, 0.03],
        "down_day_streak": [0, 0, 0],
    })

    mock_actions = [None, None, None]  # Rule never fires

    with patch("activate.features.build_features", return_value=mock_df), \
         patch("activate.sandbox.run_rule", return_value=mock_actions), \
         patch("activate.pd.read_csv", return_value=mock_df):

        result = activate.activate(mock_run_store, "run123", "rule_1", "follower_sample")

        assert result["n_rule_applies"] == 0
        assert result["already_follows_pct"] == 0.0
        assert result["avg_outcome_when_followed"] is None
        assert result["avg_outcome_when_not"] is None
        assert "Based on 0 of your 3 trades" in result["caveat"]


@pytest.fixture
def guru_store(mock_run_store):
    guru_public = {"dip": {"insights": mock_run_store["run123"]["insights"]}}
    guru_rules = {"dip": {"r1": mock_run_store["run123"]["rule_codes"]["r1"]}}
    return guru_public, guru_rules


def test_activate_run_not_found_is_not_found_error(mock_run_store):
    with pytest.raises(activate.NotFoundError, match="Run .* not found"):
        activate.activate(mock_run_store, "run999", "rule_1", "follower_sample")


def test_activate_guru_success(follower_sample_csv, guru_store):
    guru_public, guru_rules = guru_store
    mock_df = pd.DataFrame({
        "date": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"],
        "symbol": ["NVDA", "AAPL", "TSLA", "GOOGL", "MSFT"],
        "side": ["buy", "sell", "buy", "sell", "buy"],
        "ret_1d": [-0.05, -0.03, -0.04, 0.01, -0.06],
        "down_day_streak": [3, 1, 4, 0, 5],
    })
    mock_actions = ["buy", None, "buy", None, "buy"]

    with patch("activate.features.build_features", return_value=mock_df), \
         patch("activate.sandbox.run_rule", return_value=mock_actions), \
         patch("activate.pd.read_csv", return_value=mock_df), \
         patch("activate._outcome_pct", return_value=5.0):

        result = activate.activate_guru(guru_public, guru_rules, "dip", "rule_1", "follower_sample")

        assert result["n_rule_applies"] == 3
        assert result["already_follows_pct"] == pytest.approx(1.0)
        assert result["avg_outcome_when_followed"] == 5.0
        assert result["avg_outcome_when_not"] is None
        assert "Based on 3 of your 5 trades" in result["caveat"]


def test_activate_guru_unknown(guru_store):
    guru_public, guru_rules = guru_store
    with pytest.raises(activate.NotFoundError, match="Guru .* not found"):
        activate.activate_guru(guru_public, guru_rules, "nope", "rule_1", "follower_sample")


def test_activate_guru_insight_not_found(guru_store):
    guru_public, guru_rules = guru_store
    with pytest.raises(activate.NotFoundError, match="Insight .* not found"):
        activate.activate_guru(guru_public, guru_rules, "dip", "rule_999", "follower_sample")


def test_activate_guru_no_rule_code(guru_store):
    guru_public, guru_rules = guru_store
    with pytest.raises(ValueError, match="has no rule code") as exc:
        activate.activate_guru(guru_public, guru_rules, "dip", "exception_1", "follower_sample")
    assert not isinstance(exc.value, activate.NotFoundError)


def test_activate_guru_rule_code_missing(guru_store):
    guru_public, _ = guru_store
    with pytest.raises(ValueError, match="Rule code r1 not found in guru dip"):
        activate.activate_guru(guru_public, {}, "dip", "rule_1", "follower_sample")


@pytest.fixture
def mock_activate_internals(monkeypatch, guru_store, mock_run_store):
    guru_public, guru_rules = guru_store
    monkeypatch.setitem(main.guru_public, "dip", guru_public["dip"])
    monkeypatch.setitem(main.guru_rules, "dip", guru_rules["dip"])
    monkeypatch.setitem(main.runs, "run123", mock_run_store["run123"])
    mock_df = pd.DataFrame({
        "date": ["2026-01-01", "2026-01-02"],
        "symbol": ["NVDA", "AAPL"],
        "side": ["buy", "sell"],
        "down_day_streak": [3, 0],
    })
    monkeypatch.setattr(activate.features, "build_features", Mock(return_value=mock_df))
    monkeypatch.setattr(activate.sandbox, "run_rule", Mock(return_value=["buy", None]))
    monkeypatch.setattr(activate.pd, "read_csv", Mock(return_value=mock_df))
    monkeypatch.setattr(activate, "_outcome_pct", Mock(return_value=1.0))


ACTIVATE_KEYS = {"n_rule_applies", "already_follows_pct", "avg_outcome_when_followed", "avg_outcome_when_not", "caveat"}


def test_api_activate_guru(mock_activate_internals):
    r = client.post("/activate", json={"guru_id": "dip", "insight_id": "rule_1", "dataset": "follower_sample"})
    assert r.status_code == 200
    assert set(r.json().keys()) == ACTIVATE_KEYS


def test_api_activate_guru_unknown_404(mock_activate_internals):
    r = client.post("/activate", json={"guru_id": "nope", "insight_id": "rule_1", "dataset": "follower_sample"})
    assert r.status_code == 404


def test_api_activate_guru_insight_unknown_404(mock_activate_internals):
    r = client.post("/activate", json={"guru_id": "dip", "insight_id": "rule_999", "dataset": "follower_sample"})
    assert r.status_code == 404


def test_api_activate_guru_exception_insight_400(mock_activate_internals):
    r = client.post("/activate", json={"guru_id": "dip", "insight_id": "exception_1", "dataset": "follower_sample"})
    assert r.status_code == 400


def test_api_activate_both_ids_400(mock_activate_internals):
    r = client.post("/activate", json={"run_id": "run123", "guru_id": "dip", "insight_id": "rule_1", "dataset": "follower_sample"})
    assert r.status_code == 400


def test_api_activate_neither_id_400(mock_activate_internals):
    r = client.post("/activate", json={"insight_id": "rule_1", "dataset": "follower_sample"})
    assert r.status_code == 400


def test_api_activate_run_form(mock_activate_internals):
    r = client.post("/activate", json={"run_id": "run123", "insight_id": "rule_1", "dataset": "follower_sample"})
    assert r.status_code == 200
    assert set(r.json().keys()) == ACTIVATE_KEYS


def test_api_activate_run_unknown_404(mock_activate_internals):
    r = client.post("/activate", json={"run_id": "nope", "insight_id": "rule_1", "dataset": "follower_sample"})
    assert r.status_code == 404
