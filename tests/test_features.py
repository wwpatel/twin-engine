import math
import socket
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import features
from features import FEATURE_COLUMNS, build_features, load_prices, save_earnings_cache, save_price_cache

CACHE_START = pd.Timestamp("2023-10-01")
CACHE_END = pd.Timestamp("2024-06-30")
PRICE_COLS = ["open", "high", "low", "close"]
FIXTURE_DAYS = pd.bdate_range("2023-10-02", "2024-06-28", name="date")

TRADES = [
    {"date": "2024-03-04", "symbol": "AAPL", "side": "buy", "qty": 10, "price": 101.5},  # Monday
    {"date": "2024-03-13", "symbol": "msft", "side": "sell", "qty": 5, "price": 205.0},
    {"date": "2024-04-02", "symbol": "AAPL", "side": "sell", "qty": 10, "price": 99.0},
]


def _fixture_prices(base: float, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = base * np.cumprod(1 + rng.normal(0, 0.01, len(FIXTURE_DAYS)))
    return pd.DataFrame(
        {
            "open": close * 0.998,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": rng.integers(1_000_000, 5_000_000, len(FIXTURE_DAYS)).astype(float),
        },
        index=FIXTURE_DAYS,
    )


FIXTURES = {
    "AAPL": _fixture_prices(100.0, 1),
    "MSFT": _fixture_prices(200.0, 2),
    "SPY": _fixture_prices(400.0, 3),
}
EARNINGS = {
    "AAPL": [pd.Timestamp("2024-02-01"), pd.Timestamp("2024-03-07"), pd.Timestamp("2024-05-02")],
    "MSFT": None,
}


def _write_cache(cache_dir, prices=FIXTURES):
    for sym, df in prices.items():
        save_price_cache(sym, df, CACHE_START, CACHE_END, cache_dir)
    for sym, dates in EARNINGS.items():
        save_earnings_cache(sym, dates, CACHE_END, cache_dir)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("network access attempted in tests")

    monkeypatch.setattr(features, "fetch_prices", blocked)
    monkeypatch.setattr(features, "fetch_earnings_dates", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)


@pytest.fixture
def cache_dir(tmp_path):
    _write_cache(tmp_path)
    return tmp_path


def test_one_row_per_trade_with_expected_columns(cache_dir):
    df = build_features(TRADES, cache_dir=cache_dir)
    assert list(df.columns) == FEATURE_COLUMNS
    assert len(df) == len(TRADES)
    assert list(df["symbol"]) == ["AAPL", "MSFT", "AAPL"]
    assert list(df["side"]) == ["buy", "sell", "sell"]
    assert list(df["qty"]) == [10, 5, 10]
    assert list(df["price"]) == [101.5, 205.0, 99.0]
    assert list(df["date"]) == [pd.Timestamp(t["date"]) for t in TRADES]


def test_empty_trades(cache_dir):
    df = build_features([], cache_dir=cache_dir)
    assert list(df.columns) == FEATURE_COLUMNS
    assert df.empty


def test_values_computed_from_previous_close(cache_dir):
    row = build_features(TRADES[:1], cache_dir=cache_dir).iloc[0]
    # Monday 2024-03-04 trade -> as-of close is Friday 2024-03-01.
    c = FIXTURES["AAPL"]["close"].loc[: "2024-03-01"]
    s = FIXTURES["SPY"]["close"].loc[: "2024-03-01"]
    assert c.index[-1] == pd.Timestamp("2024-03-01")

    assert row["ret_1d"] == pytest.approx(c.iloc[-1] / c.iloc[-2] - 1)
    assert row["ret_3d"] == pytest.approx(c.iloc[-1] / c.iloc[-4] - 1)
    assert row["ret_5d"] == pytest.approx(c.iloc[-1] / c.iloc[-6] - 1)
    assert row["dist_from_ma20"] == pytest.approx(c.iloc[-1] / c.iloc[-20:].mean() - 1)
    assert row["spy_ret_1d"] == pytest.approx(s.iloc[-1] / s.iloc[-2] - 1)
    assert row["spy_ret_5d"] == pytest.approx(s.iloc[-1] / s.iloc[-6] - 1)

    streak = 0
    while c.iloc[-1 - streak] < c.iloc[-2 - streak]:
        streak += 1
    assert row["down_day_streak"] == streak


def test_down_day_streak(tmp_path):
    closes = [10, 11, 12, 11.5, 11, 10.5, 99]  # three down days, then trade-day spike
    days = pd.bdate_range("2024-01-02", periods=len(closes), name="date")
    df = pd.DataFrame({c: closes for c in ["open", "high", "low", "close"]}, index=days)
    df["volume"] = 1.0
    _write_cache(tmp_path, {"AAPL": df, "SPY": df})

    trade = {"date": days[-1], "symbol": "AAPL", "side": "buy", "qty": 1, "price": 99}
    row = build_features([trade], cache_dir=tmp_path).iloc[0]
    assert row["down_day_streak"] == 3
    assert row["ret_1d"] == pytest.approx(10.5 / 11 - 1)
    assert math.isnan(row["dist_from_ma20"])  # fewer than 20 prior closes


def test_days_to_next_earnings(cache_dir):
    df = build_features(TRADES, cache_dir=cache_dir)
    # AAPL as-of 2024-03-01 -> next earnings 2024-03-07.
    assert df.loc[0, "days_to_next_earnings"] == 6
    # MSFT has no earnings data -> null.
    assert pd.isna(df.loc[1, "days_to_next_earnings"])
    # AAPL as-of 2024-04-01 -> next earnings 2024-05-02.
    assert df.loc[2, "days_to_next_earnings"] == 31
    assert str(df["days_to_next_earnings"].dtype) == "Int64"


def test_no_feature_uses_same_day_or_later_data(tmp_path):
    """Corrupting the trade date and everything after must not change any feature,
    while corrupting the previous trading day must."""
    for trade in TRADES:
        trade_date = pd.Timestamp(trade["date"])

        base_dir = tmp_path / f"base-{trade_date:%Y%m%d}"
        _write_cache(base_dir)
        baseline = build_features([trade], cache_dir=base_dir)

        future = {}
        for sym, df in FIXTURES.items():
            df = df.copy()
            mask = df.index >= trade_date
            df.loc[mask, PRICE_COLS] = df.loc[mask, PRICE_COLS] * 50 + 1234.0
            future[sym] = df
        future_dir = tmp_path / f"future-{trade_date:%Y%m%d}"
        _write_cache(future_dir, future)
        corrupted = build_features([trade], cache_dir=future_dir)
        pd.testing.assert_frame_equal(baseline, corrupted)

        # Sanity check that the test is sensitive: changing the as-of day changes features.
        prev = {}
        for sym, df in FIXTURES.items():
            df = df.copy()
            as_of = df.index[df.index < trade_date][-1]
            df.loc[as_of, PRICE_COLS] = df.loc[as_of, PRICE_COLS] * 50
            prev[sym] = df
        prev_dir = tmp_path / f"prev-{trade_date:%Y%m%d}"
        _write_cache(prev_dir, prev)
        shifted = build_features([trade], cache_dir=prev_dir)
        for col in ["ret_1d", "ret_3d", "ret_5d", "dist_from_ma20", "spy_ret_1d", "spy_ret_5d"]:
            assert shifted.loc[0, col] != pytest.approx(baseline.loc[0, col]), col



def test_load_prices_uses_disk_cache(cache_dir):
    df = load_prices("AAPL", pd.Timestamp("2024-01-01"), pd.Timestamp("2024-02-01"), cache_dir=cache_dir)
    assert df.index.min() >= pd.Timestamp("2024-01-01")
    assert df.index.max() < pd.Timestamp("2024-02-01")
    pd.testing.assert_series_equal(
        df["close"], FIXTURES["AAPL"]["close"].loc["2024-01-01":"2024-01-31"], check_freq=False, check_names=False
    )


def test_load_prices_fetches_once_then_caches(tmp_path, monkeypatch):
    calls = []

    def fake_fetch(symbol, start, end):
        calls.append((symbol, start, end))
        df = FIXTURES["AAPL"]
        return df[(df.index >= start) & (df.index < end)]

    monkeypatch.setattr(features, "fetch_prices", fake_fetch)
    start, end = pd.Timestamp("2024-01-01"), pd.Timestamp("2024-03-01")
    first = load_prices("AAPL", start, end, cache_dir=tmp_path)
    assert (tmp_path / "AAPL.csv").exists()
    second = load_prices("AAPL", start, end, cache_dir=tmp_path)
    assert len(calls) == 1
    pd.testing.assert_frame_equal(first, second, check_freq=False)
