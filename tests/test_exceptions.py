import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import engine  # noqa: E402


@pytest.fixture(autouse=True)
def _no_outcomes(monkeypatch):
    monkeypatch.setattr(engine, "fetch_close_after", lambda *a, **k: None)


@pytest.fixture
def news_cache(monkeypatch):
    cache = {}
    monkeypatch.setattr(engine, "_load_news_cache", lambda: cache)
    return cache


def trade(date="2026-01-05", symbol="AAPL", side="buy"):
    return {"date": date, "symbol": symbol, "side": side, "qty": 1.0, "price": 100.0}


def rule(text, actions, coverage=0.5):
    return {"text": text, "coverage": coverage, "actions": actions, "rule_code_id": "r1"}


def test_sell_exception_with_only_buy_rule_is_broke_rule(news_cache):
    trades = [trade(side="sell")]
    kept = [rule("Buys after 3+ down days", ["buy"])]

    exceptions, summary = engine._exceptions_and_summary(trades, kept)

    assert exceptions[0]["exception_type"] == "broke_rule"
    assert exceptions[0]["broke_rule"] == "Buys after 3+ down days"
    assert exceptions[0]["note"] is None
    assert summary["n_broke_rule"] == 1
    assert summary["n_unexplained"] == 0


def test_trade_no_kept_rule_fires_is_unexplained(news_cache):
    trades = [trade(side="sell")]
    kept = [rule("Buys after 3+ down days", [None])]

    exceptions, summary = engine._exceptions_and_summary(trades, kept)

    assert exceptions[0]["exception_type"] == "unexplained"
    assert exceptions[0]["broke_rule"] is None
    assert exceptions[0]["note"] == "No kept rule covers this trade"
    assert summary["n_unexplained"] == 1


def test_highest_coverage_contradicting_rule_wins(news_cache):
    trades = [trade(side="sell")]
    kept = [
        rule("Low coverage contradicting", ["buy"], coverage=0.2),
        rule("Higher coverage contradicting", ["buy"], coverage=0.5),
        rule("Silent rule", [None], coverage=0.9),
    ]

    exceptions, _ = engine._exceptions_and_summary(trades, kept)

    assert exceptions[0]["broke_rule"] == "Higher coverage contradicting"


def test_sorting_broke_rule_first_then_by_date(news_cache):
    trades = [
        trade(date="2026-01-01", side="sell"),  # unexplained, earliest
        trade(date="2026-01-03", side="sell"),  # broke_rule
        trade(date="2026-01-02", side="sell"),  # broke_rule
    ]
    kept = [rule("Buy rule", [None, "buy", "buy"])]

    exceptions, _ = engine._exceptions_and_summary(trades, kept)

    assert [(e["exception_type"], e["date"]) for e in exceptions] == [
        ("broke_rule", "2026-01-02"),
        ("broke_rule", "2026-01-03"),
        ("unexplained", "2026-01-01"),
    ]


def test_irrelevant_headline_filtered(news_cache):
    news_cache["AAPL|2026-01-05"] = [
        {"title": "Apple unveils new iPhone", "url": "u1"},
        {"title": "Markets rally on rate hopes", "url": "u2"},
        {"title": "Why aapl is the ticker to watch", "url": "u3"},
    ]
    trades = [trade(symbol="AAPL", side="sell")]
    kept = [rule("Buy rule", [None])]

    exceptions, _ = engine._exceptions_and_summary(trades, kept)

    assert exceptions[0]["context"] == ["Apple unveils new iPhone", "Why aapl is the ticker to watch"]


def test_all_headlines_filtered_uses_fallback(news_cache):
    news_cache["AAPL|2026-01-05"] = [
        {"title": "Markets rally on rate hopes", "url": "u1"},
        {"title": "Oil prices climb", "url": "u2"},
    ]
    trades = [trade(symbol="AAPL", side="sell")]
    kept = [rule("Buy rule", [None])]

    exceptions, _ = engine._exceptions_and_summary(trades, kept)

    assert exceptions[0]["context"] == ["No clear cause in the news"]


def test_alias_match(news_cache):
    news_cache["GOOGL|2026-01-05"] = [
        {"title": "Alphabet reports earnings", "url": "u1"},
        {"title": "Unrelated markets story", "url": "u2"},
    ]
    trades = [trade(symbol="GOOGL", side="sell")]
    kept = [rule("Buy rule", [None])]

    exceptions, _ = engine._exceptions_and_summary(trades, kept)

    assert exceptions[0]["context"] == ["Alphabet reports earnings"]


def test_news_cache_file_not_written(news_cache):
    import news

    trades = [trade(symbol="AAPL", side="sell")]
    kept = [rule("Buy rule", [None])]
    engine._exceptions_and_summary(trades, kept)

    assert not os.path.exists(news.CACHE_PATH)
