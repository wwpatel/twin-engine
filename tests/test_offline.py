"""At request time only Anthropic may use the network: prices and news come from disk."""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import engine  # noqa: E402
import features  # noqa: E402


@pytest.fixture
def no_network(monkeypatch):
    def boom(*a, **k):
        pytest.fail("network used")

    monkeypatch.setattr(features, "fetch_prices", boom)
    monkeypatch.setattr(features, "fetch_earnings_dates", boom)
    monkeypatch.setitem(sys.modules, "yfinance", None)  # any `import yfinance` now fails


def _trade(date="2025-01-10"):
    return {"date": date, "symbol": "AAA", "side": "buy", "qty": 1.0, "price": 100.0}


def test_build_features_offline_with_empty_cache_does_not_fetch(no_network, tmp_path):
    df = features.build_features([_trade()], cache_dir=tmp_path, allow_fetch=False)
    assert len(df) == 1
    assert pd.isna(df.loc[0, "ret_1d"])


def test_build_features_offline_uses_cached_prices(no_network, tmp_path):
    idx = pd.date_range("2024-12-01", "2025-01-09", freq="B")
    prices = pd.DataFrame({c: 100.0 for c in features.PRICE_COLUMNS}, index=idx)
    prices["close"] = [100.0 + i for i in range(len(idx))]
    for sym in ("AAA", features.BENCHMARK):
        features.save_price_cache(sym, prices, pd.Timestamp("2024-11-01"), pd.Timestamp("2025-02-01"), tmp_path)

    df = features.build_features([_trade()], cache_dir=tmp_path, allow_fetch=False)
    assert df.loc[0, "ret_1d"] == pytest.approx(prices["close"].iloc[-1] / prices["close"].iloc[-2] - 1)


def test_outcome_comes_from_cached_closes_and_is_null_when_missing(no_network, monkeypatch, tmp_path):
    idx = pd.date_range("2025-01-06", periods=10, freq="B")
    pd.DataFrame({"close": [100.0 + i for i in range(10)]}, index=idx).rename_axis("date").to_csv(
        tmp_path / "AAA.close.csv"
    )
    monkeypatch.setattr(engine, "PRICE_DIR", str(tmp_path))
    monkeypatch.setattr(engine, "_CLOSE_CACHE", {})

    # trade on day 0 (Jan 6, close 100): 5 trading days later the cached close is 105
    assert engine.fetch_close_after("AAA", "2025-01-06") == 105.0
    assert engine._outcome_pct({"symbol": "AAA", "date": "2025-01-06", "price": 100.0, "side": "buy"}) == 5.0
    # symbol not in the cache, or horizon beyond the cache: null, never a fetch
    assert engine._outcome_pct({"symbol": "ZZZ", "date": "2025-01-06", "price": 100.0, "side": "buy"}) is None
    assert engine.fetch_close_after("AAA", "2025-01-17") is None
