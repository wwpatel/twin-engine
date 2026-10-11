"""Download daily prices once into data/prices so runs never need Yahoo at request time.

Usage (from the repo root): python data/build_price_cache.py

For every symbol in data/*.csv plus SPY this writes, under data/prices:
  <SYM>.csv / <SYM>.meta.json   adjusted OHLCV for features (read by features.load_prices)
  <SYM>.earnings.json           earnings dates for features
  <SYM>.close.csv               unadjusted closes for outcome_pct (read by engine.fetch_close_after)
The range runs from 60 days before the earliest trade to 14 days after the latest, which covers
the 5-trading-day outcome horizon.
"""
import csv
import glob
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import features  # noqa: E402

OUTCOME_BUFFER_DAYS = 14


def scan_trade_csvs(pattern: str = "data/*.csv") -> tuple[set[str], list[pd.Timestamp]]:
    symbols, dates = set(), []
    for path in sorted(glob.glob(pattern)):
        with open(path) as f:
            reader = csv.DictReader(f)
            if not {"date", "symbol"} <= set(reader.fieldnames or []):
                continue
            for row in reader:
                symbols.add(row["symbol"].strip().upper())
                dates.append(pd.Timestamp(row["date"].strip()))
    return symbols, dates


def fetch_raw_closes(symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    import yfinance as yf

    raw = yf.download(
        symbol,
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        interval="1d",
        auto_adjust=False,
        progress=False,
        multi_level_index=False,
    )
    closes = raw["Close"].astype(float)
    closes.index = pd.to_datetime(closes.index).tz_localize(None).normalize()
    closes.index.name = "date"
    return closes.rename("close")


def build(cache_dir: Path = features.PRICE_CACHE_DIR) -> None:
    symbols, dates = scan_trade_csvs()
    if not dates:
        sys.exit("no trade CSVs found in data/")
    start = min(dates) - pd.Timedelta(days=features.LOOKBACK_DAYS)
    end = min(max(dates) + pd.Timedelta(days=OUTCOME_BUFFER_DAYS), pd.Timestamp.today().normalize())
    print(f"{len(symbols)} symbols + {features.BENCHMARK}, {start.date()} to {end.date()}")

    for symbol in sorted(symbols | {features.BENCHMARK}):
        prices = features.fetch_prices(symbol, start, end)
        if prices.empty:
            print(f"  {symbol}: no price data, skipped", file=sys.stderr)
            continue
        features.save_price_cache(symbol, prices, start, end, cache_dir)
        if symbol != features.BENCHMARK:
            earnings = features.fetch_earnings_dates(symbol)
            features.save_earnings_cache(symbol, earnings, pd.Timestamp.today().normalize(), cache_dir)
        closes = fetch_raw_closes(symbol, start, end)
        closes.to_csv(Path(cache_dir) / f"{symbol}.close.csv", date_format="%Y-%m-%d")
        print(f"  {symbol}: {len(prices)} price rows, {len(closes)} raw closes")


if __name__ == "__main__":
    build()
