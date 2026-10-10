import json
import os
import tempfile

import pytest

from news import get_headlines


@pytest.fixture
def cache_file():
    cache_content = {
        "NVDA|2026-01-15": [
            {"title": "NVIDIA reports strong earnings", "source": "TechNews", "published": "Jan 14, 2026"},
            {"title": "AI chip demand surges", "source": "Bloomberg", "published": "Jan 13, 2026"},
            {"title": "NVIDIA stock hits new high", "source": "Reuters", "published": "Jan 12, 2026"},
        ],
        "AAPL|2026-01-16": [
            {"title": "Apple announces new iPhone", "source": "TechCrunch", "published": "Jan 15, 2026"},
        ],
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(cache_content, f)
        cache_path = f.name

    import news
    original_cache = news.CACHE_PATH
    news.CACHE_PATH = cache_path

    yield cache_path

    news.CACHE_PATH = original_cache
    os.unlink(cache_path)


def test_get_headlines_from_cache(cache_file):
    headlines = get_headlines("NVDA", "2026-01-15")
    assert len(headlines) == 3
    assert headlines[0]["title"] == "NVIDIA reports strong earnings"
    assert headlines[0]["source"] == "TechNews"
    assert headlines[0]["published"] == "Jan 14, 2026"


def test_get_headlines_cache_miss_returns_empty(cache_file):
    headlines = get_headlines("TSLA", "2026-01-20")
    assert headlines == []


def test_get_headlines_partial_cache(cache_file):
    headlines = get_headlines("AAPL", "2026-01-16")
    assert len(headlines) == 1
    assert headlines[0]["title"] == "Apple announces new iPhone"
