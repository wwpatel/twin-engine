"""Precompute the news cache for every (symbol, date) in one or more trade CSVs.

Usage: python precompute_news.py [extra.csv ...]
Reads data/sample_trades.csv plus any CSV paths given, fetches headlines with 4 threads, and
writes data/news_cache.json after every result. Needs BRIGHTDATA_API_KEY and BRIGHTDATA_ZONE.
"""
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import news
from parser import load_trades

DEFAULT_CSV = "data/sample_trades.csv"
THREADS = 4
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 2
PROGRESS_EVERY = 20


def load_cache() -> dict:
    try:
        with open(news.CACHE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_cache(cache: dict) -> None:
    os.makedirs(os.path.dirname(news.CACHE_PATH) or ".", exist_ok=True)
    tmp = f"{news.CACHE_PATH}.tmp"
    with open(tmp, "w") as f:
        json.dump(cache, f)
    os.replace(tmp, news.CACHE_PATH)  # a crash mid-write never corrupts the cache


def unique_lookups(csv_paths: list[str]) -> list[tuple[str, str]]:
    keys = set()
    for path in csv_paths:
        for trade in load_trades(path):
            keys.add((trade["symbol"], str(trade["date"])[:10]))
    return sorted(keys)


def fetch_with_retry(symbol: str, date: str, api_key: str, zone: str) -> list[dict] | None:
    """Return headlines, or None if every attempt failed."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return news.fetch_headlines(symbol, date, api_key, zone)
        except news.RetryableError as e:
            if attempt == MAX_ATTEMPTS:
                print(f"giving up on {symbol}|{date}: {e}", file=sys.stderr)
                return None
            time.sleep(BACKOFF_SECONDS * 2 ** (attempt - 1))
        except Exception as e:
            print(f"failed {symbol}|{date}: {e!r}", file=sys.stderr)
            return None


def precompute_news(csv_paths: list[str]) -> None:
    api_key = os.environ.get("BRIGHTDATA_API_KEY")
    zone = os.environ.get("BRIGHTDATA_ZONE")
    if not api_key or not zone:
        sys.exit("BRIGHTDATA_API_KEY and BRIGHTDATA_ZONE must be set")

    lookups = unique_lookups(csv_paths)
    cache = load_cache()
    todo = [(s, d) for s, d in lookups if not cache.get(f"{s}|{d}")]
    print(f"{len(lookups)} unique lookups, {len(lookups) - len(todo)} already cached, {len(todo)} to fetch")

    lock = threading.Lock()
    done = 0
    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        futures = {pool.submit(fetch_with_retry, s, d, api_key, zone): (s, d) for s, d in todo}
        for future in as_completed(futures):
            symbol, date = futures[future]
            headlines = future.result()
            with lock:
                done += 1
                if headlines is not None:
                    cache[f"{symbol}|{date}"] = headlines
                    save_cache(cache)
                if done % PROGRESS_EVERY == 0:
                    print(f"{done}/{len(todo)} fetched")

    with_headlines = sum(1 for s, d in lookups if cache.get(f"{s}|{d}"))
    print(f"Done: {len(lookups)} lookups, {with_headlines} with headlines "
          f"({with_headlines / len(lookups):.0%})" if lookups else "Done: no lookups")


if __name__ == "__main__":
    precompute_news([DEFAULT_CSV] + sys.argv[1:])
