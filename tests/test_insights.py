import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import insights  # noqa: E402


def test_build_insights_with_kept_rules():
    """Test that insights are built for kept rules."""
    result = {
        "hypotheses": [
            {"text": "Buys after 3+ down days", "status": "kept", "discovery_match": 0.8, "holdout_match": 0.75, "coverage": 0.3},
            {"text": "Sells when overbought", "status": "rejected", "discovery_match": 0.5, "holdout_match": 0.4},
            {"text": "Buys before earnings", "status": "kept", "discovery_match": 0.9, "holdout_match": 0.85, "coverage": 0.2},
        ],
        "baseline": {"holdout_match": 0.4},
        "exceptions": [],
    }

    insights_list = insights.build_insights(result)

    # Should have 2 rule insights (one per kept rule)
    rule_insights = [i for i in insights_list if i["kind"] == "rule"]
    assert len(rule_insights) == 2

    # Check first rule insight
    assert rule_insights[0]["id"] == "rule_1"
    assert rule_insights[0]["title"] == "Buys after 3+ down days"
    assert rule_insights[0]["plain"] == "Buys after 3+ down days"
    assert rule_insights[0]["kind"] == "rule"
    assert rule_insights[0]["rule_code_id"] == "r1"
    assert rule_insights[0]["evidence"]["discovery_match"] == 0.8
    assert rule_insights[0]["evidence"]["holdout_match"] == 0.75
    assert rule_insights[0]["evidence"]["baseline_holdout_match"] == 0.4

    # Check second rule insight
    assert rule_insights[1]["id"] == "rule_2"
    assert rule_insights[1]["title"] == "Buys before earnings"
    assert rule_insights[1]["rule_code_id"] == "r2"


def test_build_insights_with_exception_patterns():
    """Test that insights are built for exception patterns."""
    result = {
        "hypotheses": [],
        "baseline": {"holdout_match": 0.4},
        "exceptions": [
            {"date": "2026-01-01", "symbol": "NVDA", "side": "buy", "broke_rule": "Buys after 3+ down days", "context": ["Earnings beat"]},
            {"date": "2026-01-02", "symbol": "NVDA", "side": "sell", "broke_rule": "Buys after 3+ down days", "context": ["Market rally"]},
            {"date": "2026-01-03", "symbol": "AAPL", "side": "buy", "broke_rule": "Buys after 3+ down days", "context": ["Product launch"]},
            {"date": "2026-01-04", "symbol": "AAPL", "side": "sell", "broke_rule": "Buys after 3+ down days", "context": ["Earnings miss"]},
            {"date": "2026-01-05", "symbol": "TSLA", "side": "buy", "broke_rule": "Buys after 3+ down days", "context": ["CEO tweet"]},
        ],
    }

    insights_list = insights.build_insights(result)

    # Should have exception pattern insights
    exception_insights = [i for i in insights_list if i["kind"] == "exception_pattern"]
    assert len(exception_insights) > 0

    # Check that rule_code_id is null for exception patterns
    for exc in exception_insights:
        assert exc["rule_code_id"] is None
        assert exc["kind"] == "exception_pattern"
        assert exc["evidence"]["n_trades"] is not None
        assert exc["evidence"]["discovery_match"] is None
        assert exc["evidence"]["holdout_match"] is None


def test_build_insights_empty_result():
    """Test that insights works with empty result."""
    result = {
        "hypotheses": [],
        "baseline": {"holdout_match": 0.4},
        "exceptions": [],
    }

    insights_list = insights.build_insights(result)

    assert insights_list == []


def test_build_insights_mixed():
    """Test insights with both rules and exceptions."""
    result = {
        "hypotheses": [
            {"text": "Buys after 3+ down days", "status": "kept", "discovery_match": 0.8, "holdout_match": 0.75, "coverage": 0.3},
        ],
        "baseline": {"holdout_match": 0.4},
        "exceptions": [
            {"date": "2026-01-01", "symbol": "NVDA", "side": "buy", "broke_rule": "Buys after 3+ down days", "context": ["Earnings beat"]},
            {"date": "2026-01-02", "symbol": "NVDA", "side": "sell", "broke_rule": "Buys after 3+ down days", "context": ["Market rally"]},
        ],
    }

    insights_list = insights.build_insights(result)

    # Should have 1 rule insight and at least 1 exception pattern
    rule_insights = [i for i in insights_list if i["kind"] == "rule"]
    exception_insights = [i for i in insights_list if i["kind"] == "exception_pattern"]

    assert len(rule_insights) == 1
    assert len(exception_insights) >= 1

    # Verify rule insight has rule_code_id
    assert rule_insights[0]["rule_code_id"] == "r1"

    # Verify exception insights don't have rule_code_id
    for exc in exception_insights:
        assert exc["rule_code_id"] is None
