import json
import os
from datetime import datetime, timedelta

import requests


CACHE_PATH = "data/news_cache.json"


def get_headlines(symbol: str, date: str) -> list[dict]:
    cache_key = f"{symbol}|{date}"

    try:
        with open(CACHE_PATH) as f:
            cache = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        cache = {}

    if cache_key in cache:
        return cache[cache_key]

    api_key = os.environ.get("BRIGHTDATA_API_KEY")
    zone = os.environ.get("BRIGHTDATA_ZONE")

    if not api_key or not zone:
        return []

    try:
        target_date = datetime.fromisoformat(date)
        end_date = target_date - timedelta(days=1)
        start_date = end_date - timedelta(days=2)

        query = f"{symbol}+stock"
        url = f"https://www.google.com/search?q={query}&tbm=nws&tbs=cdr:1,cd_min:{start_date.strftime('%Y/%m/%d')},cd_max:{end_date.strftime('%Y/%m/%d')}&brd_json=1"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "zone": zone,
            "url": url,
            "format": "raw",
        }

        response = requests.post(
            "https://api.brightdata.com/request",
            headers=headers,
            json=payload,
            timeout=30,
        )

        if response.status_code != 200:
            return []

        data = response.json()

        headlines = []
        if "organic" in data:
            for item in data["organic"][:3]:
                headlines.append({
                    "title": item.get("title", ""),
                    "source": item.get("source", ""),
                    "published": item.get("date", ""),
                })

        cache[cache_key] = headlines

        os.makedirs(os.path.dirname(CACHE_PATH) or ".", exist_ok=True)
        with open(CACHE_PATH, "w") as f:
            json.dump(cache, f)

        return headlines
    except Exception:
        return []
