import json
import os
import re
import sys
from datetime import datetime, timedelta

import requests


CACHE_PATH = "data/news_cache.json"
API_URL = "https://api.brightdata.com/request"
WINDOW_DAYS = 7
MAX_HEADLINES = 3


class RetryableError(Exception):
    """Rate limit, server error, or an empty/non-JSON body: worth trying again."""


def _log(message: str) -> None:
    print(f"news: {message}", file=sys.stderr)


class NewsUnavailable(Exception):
    """Live lookup could not run: missing credentials or a failed Bright Data request."""


def _read_cache() -> dict:
    try:
        with open(CACHE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def get_headlines(symbol: str, date: str, use_cache: bool = True) -> list[dict]:
    try:
        return fetch_live_headlines(symbol, date, use_cache=use_cache)
    except Exception as e:
        _log(f"get_headlines({symbol!r}, {date!r}) failed: {e!r}")
        return []


def fetch_live_headlines(symbol: str, date: str, use_cache: bool = True) -> list[dict]:
    """Return headlines; raises NewsUnavailable if credentials are missing, else propagates fetch errors."""
    cache_key = f"{symbol}|{date}"
    cache = _read_cache()
    if use_cache and cache_key in cache:
        return cache[cache_key]

    api_key = os.environ.get("BRIGHTDATA_API_KEY")
    zone = os.environ.get("BRIGHTDATA_ZONE")
    if not api_key or not zone:
        raise NewsUnavailable("BRIGHTDATA_API_KEY or BRIGHTDATA_ZONE not set")

    headlines = fetch_headlines(symbol, date, api_key, zone)

    cache[cache_key] = headlines
    os.makedirs(os.path.dirname(CACHE_PATH) or ".", exist_ok=True)
    with open(CACHE_PATH, "w") as f:
        json.dump(cache, f)

    return headlines


def fetch_headlines(symbol: str, date: str, api_key: str, zone: str) -> list[dict]:
    """Fetch up to 3 headlines published before `date`. Raises RetryableError on 429/5xx/bad body."""
    trade_date = datetime.fromisoformat(date).date()
    end_date = trade_date - timedelta(days=1)
    start_date = end_date - timedelta(days=WINDOW_DAYS)

    # Google's custom date range takes MM/DD/YYYY; other formats silently return nothing.
    url = (
        f"https://www.google.com/search?q={symbol}+stock&tbm=nws&gl=us&hl=en"
        f"&tbs=cdr:1,cd_min:{start_date:%m/%d/%Y},cd_max:{end_date:%m/%d/%Y}&brd_json=1"
    )
    response = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"zone": zone, "url": url, "format": "raw"},
        timeout=60,
    )
    if response.status_code == 429 or response.status_code >= 500:
        raise RetryableError(f"HTTP {response.status_code}")
    if response.status_code != 200:
        raise ValueError(f"HTTP {response.status_code}")
    try:
        data = response.json()
    except ValueError as e:
        raise RetryableError(f"non-JSON body ({len(response.content)} bytes)") from e

    return parse_headlines(data, trade_date, start_date, end_date)


def parse_headlines(data: dict, trade_date, start_date, end_date) -> list[dict]:
    items = data.get("news") or []
    parsed = [(item, _parse_date(item.get("date"))) for item in items]

    # The date range worked if every absolute date we can read falls inside it.
    absolute = [d for _, d in parsed if d is not None]
    range_confirmed = bool(absolute) and all(start_date <= d <= end_date for d in absolute)

    headlines = []
    for item, published in parsed:
        if published is not None:
            if published >= trade_date:
                continue
        elif not range_confirmed:
            continue  # relative date ("3 days ago") and no proof the range applied: don't guess
        headlines.append({
            "title": item.get("title", ""),
            "source": item.get("source", ""),
            "published": item.get("date", ""),
        })
        if len(headlines) == MAX_HEADLINES:
            break
    return headlines


def _parse_date(text):
    """Parse an absolute date like 'Mar 7, 2026'; return None for relative or unreadable dates."""
    if not text or re.search(r"\bago\b", text, re.IGNORECASE):
        return None
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None
