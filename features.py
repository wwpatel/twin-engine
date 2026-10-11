"""Per-trade feature engineering.

Every feature for a trade on date D is computed from data available at the
close of the last trading day strictly before D (the "as-of" day). Nothing
from D itself, or later, is used.
"""

from __future__ import annotations

import json
from pathlib import Path
import pandas as pd

PRICE_CACHE_DIR = Path("data/prices")
BENCHMARK = "SPY"
PRICE_COLUMNS = ["open", "high", "low", "close", "volume"]
FEATURE_COLUMNS = [
    "date",
    "symbol",
    "side",
    "qty",
    "price",
    "ret_1d",
    "ret_3d",
    "ret_5d",
    "down_day_streak",
    "dist_from_ma20",
    "spy_ret_1d",
    "spy_ret_5d",
    "days_to_next_earnings",
]
# Calendar-day lookback before the earliest trade; enough for a 20-day MA.
LOOKBACK_DAYS = 60


def fetch_prices(symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Download adjusted daily OHLCV for [start, end) from yfinance."""
    import yfinance as yf

    raw = yf.download(
        symbol,
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        interval="1d",
        auto_adjust=True,
        progress=False,
        multi_level_index=False,
    )
    if raw is None or raw.empty:
        return _empty_prices()
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    df = raw.rename(columns=str.lower)[PRICE_COLUMNS]
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df.index.name = "date"
    return df


def fetch_earnings_dates(symbol: str) -> list[pd.Timestamp] | None:
    """Return known past and scheduled earnings dates, or None if unavailable."""
    try:
        import yfinance as yf

        df = yf.Ticker(symbol).get_earnings_dates(limit=100)
    except Exception:
        return None
    if df is None or df.empty:
        return None
    idx = pd.to_datetime(df.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    return sorted(set(idx.normalize()))


def _empty_prices() -> pd.DataFrame:
    return pd.DataFrame(columns=PRICE_COLUMNS, index=pd.DatetimeIndex([], name="date"), dtype=float)


def _price_paths(symbol: str, cache_dir: Path) -> tuple[Path, Path]:
    return cache_dir / f"{symbol}.csv", cache_dir / f"{symbol}.meta.json"


def _earnings_path(symbol: str, cache_dir: Path) -> Path:
    return cache_dir / f"{symbol}.earnings.json"


def save_price_cache(
    symbol: str,
    prices: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    cache_dir: Path = PRICE_CACHE_DIR,
) -> None:
    """Write prices plus the [start, end) range they were fetched for."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    csv_path, meta_path = _price_paths(symbol, cache_dir)
    out = prices[PRICE_COLUMNS].sort_index()
    out.index.name = "date"
    out.to_csv(csv_path, date_format="%Y-%m-%d")
    meta_path.write_text(
        json.dumps({"start": pd.Timestamp(start).strftime("%Y-%m-%d"), "end": pd.Timestamp(end).strftime("%Y-%m-%d")})
    )


def save_earnings_cache(
    symbol: str,
    dates: list[pd.Timestamp] | None,
    fetched_on: pd.Timestamp,
    cache_dir: Path = PRICE_CACHE_DIR,
) -> None:
    """Write earnings dates (None = unavailable) and the date they were fetched."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_on": pd.Timestamp(fetched_on).strftime("%Y-%m-%d"),
        "dates": None if dates is None else [pd.Timestamp(d).strftime("%Y-%m-%d") for d in dates],
    }
    _earnings_path(symbol, cache_dir).write_text(json.dumps(payload))


def load_prices(
    symbol: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    cache_dir: Path = PRICE_CACHE_DIR,
    allow_fetch: bool = True,
) -> pd.DataFrame:
    """Daily prices covering [start, end), served from disk cache when possible.

    With allow_fetch=False the network is never used: whatever the cache holds is returned
    (empty if the symbol is not cached).
    """
    start, end = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    cache_dir = Path(cache_dir)
    csv_path, meta_path = _price_paths(symbol, cache_dir)

    cached = None
    if csv_path.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text())
        c_start, c_end = pd.Timestamp(meta["start"]), pd.Timestamp(meta["end"])
        cached = pd.read_csv(csv_path, index_col="date", parse_dates=["date"])
        if c_start <= start and end <= c_end or not allow_fetch:
            return cached.loc[(cached.index >= start) & (cached.index < end)]
        start, end = min(start, c_start), max(end, c_end)

    if not allow_fetch:
        return _empty_prices()

    fresh = fetch_prices(symbol, start, end)
    if cached is not None:
        fresh = pd.concat([cached, fresh])
        fresh = fresh[~fresh.index.duplicated(keep="last")]
    save_price_cache(symbol, fresh, start, end, cache_dir)
    return fresh.sort_index()


def load_earnings_dates(
    symbol: str,
    needed_through: pd.Timestamp,
    cache_dir: Path = PRICE_CACHE_DIR,
    allow_fetch: bool = True,
) -> list[pd.Timestamp] | None:
    """Earnings dates from cache; refetch if the cache predates `needed_through`.

    With allow_fetch=False the cache is used as is and None is returned when it is missing.
    """
    path = _earnings_path(symbol, Path(cache_dir))
    if path.exists():
        payload = json.loads(path.read_text())
        if not allow_fetch or pd.Timestamp(payload["fetched_on"]) >= needed_through:
            dates = payload["dates"]
            return None if dates is None else [pd.Timestamp(d) for d in dates]
    if not allow_fetch:
        return None
    dates = fetch_earnings_dates(symbol)
    save_earnings_cache(symbol, dates, pd.Timestamp.today().normalize(), cache_dir)
    return dates


def _history_before(close: pd.Series, trade_date: pd.Timestamp) -> pd.Series:
    """Closes strictly before the trade date; the last value is the as-of close."""
    return close[close.index < trade_date].dropna()


def _ret(hist: pd.Series, n: int) -> float:
    if len(hist) <= n:
        return float("nan")
    return float(hist.iloc[-1] / hist.iloc[-1 - n] - 1.0)


def _down_day_streak(hist: pd.Series) -> float:
    if len(hist) < 2:
        return float("nan")
    streak = 0
    values = hist.to_numpy()
    for i in range(len(values) - 1, 0, -1):
        if values[i] < values[i - 1]:
            streak += 1
        else:
            break
    return float(streak)


def _dist_from_ma(hist: pd.Series, window: int = 20) -> float:
    if len(hist) < window:
        return float("nan")
    return float(hist.iloc[-1] / hist.iloc[-window:].mean() - 1.0)


def _days_to_next_earnings(
    earnings: list[pd.Timestamp] | None, as_of: pd.Timestamp | None
):
    if earnings is None or as_of is None:
        return pd.NA
    upcoming = [d for d in earnings if d > as_of]
    if not upcoming:
        return pd.NA
    return int((min(upcoming) - as_of).days)


def build_features(
    trades: list[dict],
    cache_dir: Path | str = PRICE_CACHE_DIR,
    allow_fetch: bool = True,
) -> pd.DataFrame:
    """Build one feature row per trade.

    Each trade needs `date`, `symbol`, `side`, `qty`, `price`. Features are
    computed as of the close of the last trading day before the trade date.
    `days_to_next_earnings` is calendar days from that as-of day to the next
    earnings date after it, or null when earnings data is unavailable.
    """
    cache_dir = Path(cache_dir)
    if not trades:
        return pd.DataFrame(columns=FEATURE_COLUMNS)

    dates = [pd.Timestamp(t["date"]).normalize() for t in trades]
    start = min(dates) - pd.Timedelta(days=LOOKBACK_DAYS)
    end = max(dates)  # exclusive: never load the latest trade date itself

    symbols = sorted({str(t["symbol"]).upper() for t in trades})
    closes = {
        sym: load_prices(sym, start, end, cache_dir=cache_dir, allow_fetch=allow_fetch)["close"].astype(float)
        for sym in sorted(set(symbols) | {BENCHMARK})
    }
    earnings = {sym: load_earnings_dates(sym, end, cache_dir=cache_dir, allow_fetch=allow_fetch) for sym in symbols}

    rows = []
    for trade, trade_date in zip(trades, dates):
        sym = str(trade["symbol"]).upper()
        hist = _history_before(closes[sym], trade_date)
        spy_hist = _history_before(closes[BENCHMARK], trade_date)
        as_of = hist.index[-1] if len(hist) else None
        rows.append(
            {
                "date": trade_date,
                "symbol": sym,
                "side": trade["side"],
                "qty": trade["qty"],
                "price": trade["price"],
                "ret_1d": _ret(hist, 1),
                "ret_3d": _ret(hist, 3),
                "ret_5d": _ret(hist, 5),
                "down_day_streak": _down_day_streak(hist),
                "dist_from_ma20": _dist_from_ma(hist, 20),
                "spy_ret_1d": _ret(spy_hist, 1),
                "spy_ret_5d": _ret(spy_hist, 5),
                "days_to_next_earnings": _days_to_next_earnings(earnings[sym], as_of),
            }
        )

    df = pd.DataFrame(rows, columns=FEATURE_COLUMNS)
    df["days_to_next_earnings"] = df["days_to_next_earnings"].astype("Int64")
    return df
