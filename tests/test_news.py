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


FIXTURE_RESPONSE = {
    "general": {"search_type": "news"},
    "news": [
        {"title": "On the trade date", "source": "A", "date": "Mar 14, 2026"},
        {"title": "Day before", "source": "B", "date": "Mar 13, 2026", "link": "x", "image_base64": "y"},
        {"title": "Week earlier", "source": "C", "date": "Mar 7, 2026"},
        {"title": "Relative date", "source": "D", "date": "3 days ago"},
        {"title": "Third", "source": "E", "date": "Mar 10, 2026"},
        {"title": "Fourth", "source": "F", "date": "Mar 9, 2026"},
    ],
}


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text="{}"):
        self.status_code = status_code
        self._payload = payload
        self.content = text.encode()

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


@pytest.fixture
def empty_cache(monkeypatch, tmp_path):
    import news

    monkeypatch.setattr(news, "CACHE_PATH", str(tmp_path / "cache.json"))
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
    monkeypatch.setenv("BRIGHTDATA_ZONE", "test-zone")
    return news


def test_parse_headlines_filters_and_limits():
    from datetime import date

    import news

    # The trade-date item is outside the requested range, so the range is not confirmed:
    # it is dropped, the relative-date item is dropped, and the rest are capped at 3.
    out = news.parse_headlines(FIXTURE_RESPONSE, date(2026, 3, 14), date(2026, 3, 6), date(2026, 3, 13))
    assert [h["title"] for h in out] == ["Day before", "Week earlier", "Third"]
    assert set(out[0]) == {"title", "source", "published"}
    assert out[0]["published"] == "Mar 13, 2026"


def test_parse_headlines_keeps_relative_dates_only_when_range_confirmed():
    from datetime import date

    import news

    args = (date(2026, 3, 14), date(2026, 3, 6), date(2026, 3, 13))
    confirmed = {"news": [
        {"title": "Dated", "source": "A", "date": "Mar 12, 2026"},
        {"title": "Relative", "source": "B", "date": "3 days ago"},
    ]}
    assert [h["title"] for h in news.parse_headlines(confirmed, *args)] == ["Dated", "Relative"]

    unconfirmed = {"news": [
        {"title": "Out of range", "source": "A", "date": "Jan 1, 2020"},
        {"title": "Relative", "source": "B", "date": "3 days ago"},
    ]}
    assert [h["title"] for h in news.parse_headlines(unconfirmed, *args)] == ["Out of range"]

    only_relative = {"news": [{"title": "Relative", "source": "B", "date": "3 days ago"}]}
    assert news.parse_headlines(only_relative, *args) == []


def test_get_headlines_builds_us_english_request_and_caches(empty_cache, monkeypatch):
    news = empty_cache
    sent = {}

    def fake_post(url, headers, json, timeout):
        sent["body"] = json
        sent["auth"] = headers["Authorization"]
        return FakeResponse(200, FIXTURE_RESPONSE)

    monkeypatch.setattr(news.requests, "post", fake_post)
    out = news.get_headlines("NVDA", "2026-03-14")
    assert len(out) == 3
    url = sent["body"]["url"]
    assert "gl=us" in url and "hl=en" in url and "brd_json=1" in url and "tbm=nws" in url
    assert "cd_min:03/06/2026" in url and "cd_max:03/13/2026" in url
    assert sent["body"]["format"] == "raw"

    monkeypatch.setattr(news.requests, "post", lambda *a, **k: pytest.fail("cache should be used"))
    assert news.get_headlines("NVDA", "2026-03-14") == out


def test_get_headlines_never_raises_and_does_not_cache_failures(empty_cache, monkeypatch, capsys):
    news = empty_cache
    monkeypatch.setattr(news.requests, "post", lambda *a, **k: FakeResponse(429))
    assert news.get_headlines("NVDA", "2026-03-14") == []
    assert "429" in capsys.readouterr().err
    assert not os.path.exists(news.CACHE_PATH)

    monkeypatch.setattr(news.requests, "post", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert news.get_headlines("NVDA", "2026-03-14") == []


def test_use_cache_false_bypasses_cache_but_still_writes(empty_cache, monkeypatch):
    news = empty_cache
    monkeypatch.setattr(news.requests, "post", lambda *a, **k: FakeResponse(200, FIXTURE_RESPONSE))
    assert len(news.get_headlines("NVDA", "2026-03-14")) == 3

    calls = [0]

    def counting_post(*a, **k):
        calls[0] += 1
        return FakeResponse(200, FIXTURE_RESPONSE)

    monkeypatch.setattr(news.requests, "post", counting_post)
    out = news.get_headlines("NVDA", "2026-03-14", use_cache=False)
    assert calls[0] == 1
    assert len(out) == 3

    monkeypatch.setattr(news.requests, "post", lambda *a, **k: pytest.fail("cache should be used"))
    assert news.get_headlines("NVDA", "2026-03-14", use_cache=True) == out


def test_fetch_live_headlines_raises_news_unavailable_without_credentials(empty_cache, monkeypatch):
    news = empty_cache
    monkeypatch.delenv("BRIGHTDATA_API_KEY", raising=False)
    with pytest.raises(news.NewsUnavailable):
        news.fetch_live_headlines("NVDA", "2026-03-14")
    assert news.get_headlines("NVDA", "2026-03-14") == []
