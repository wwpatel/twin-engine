from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

import main
import news
from main import app

client = TestClient(app)

ITEMS = [{"title": "a", "source": "b", "published": "c"}, {"title": "d", "source": "e", "published": "f"}]


@pytest.fixture(autouse=True)
def _clear_news_calls():
    main._news_calls.clear()
    yield
    main._news_calls.clear()


def test_news_live_call_shape(monkeypatch):
    mock = Mock(return_value=ITEMS)
    monkeypatch.setattr(main.news, "fetch_live_headlines", mock)
    r = client.get("/news", params={"symbol": "NVDA", "date": "2026-03-14"})
    assert r.status_code == 200
    assert r.json() == {"symbol": "NVDA", "date": "2026-03-14", "items": ITEMS, "source": "live"}
    mock.assert_called_once_with("NVDA", "2026-03-14", use_cache=False)


def test_news_calls_bright_data_not_just_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
    monkeypatch.setenv("BRIGHTDATA_ZONE", "z")
    monkeypatch.setattr(news, "CACHE_PATH", str(tmp_path / "cache.json"))
    post = Mock(return_value=Mock(status_code=200, json=lambda: {
        "general": {"search_type": "news"},
        "news": [{"title": "t", "source": "s", "date": "Mar 13, 2026"}],
    }))
    monkeypatch.setattr(news.requests, "post", post)
    r = client.get("/news", params={"symbol": "NVDA", "date": "2026-03-14"})
    assert r.status_code == 200
    assert r.json()["items"] == [{"title": "t", "source": "s", "published": "Mar 13, 2026"}]
    assert r.json()["source"] == "live"
    post.assert_called_once()
    _, kwargs = post.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer test-key"
    assert kwargs["json"]["zone"] == "z"
    assert "test-key" not in r.text


def test_news_live_bypasses_cache_hit(monkeypatch, tmp_path):
    import json as _json

    monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
    monkeypatch.setenv("BRIGHTDATA_ZONE", "z")
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(_json.dumps({
        "NVDA|2026-03-14": [{"title": "cached", "source": "x", "published": "Mar 12, 2026"}],
    }))
    monkeypatch.setattr(news, "CACHE_PATH", str(cache_path))
    post = Mock(return_value=Mock(status_code=200, json=lambda: {
        "general": {"search_type": "news"},
        "news": [{"title": "t", "source": "s", "date": "Mar 13, 2026"}],
    }))
    monkeypatch.setattr(news.requests, "post", post)
    r = client.get("/news", params={"symbol": "NVDA", "date": "2026-03-14"})
    assert r.status_code == 200
    assert r.json()["items"] == [{"title": "t", "source": "s", "published": "Mar 13, 2026"}]
    assert r.json()["source"] == "live"
    post.assert_called_once()
    assert _json.loads(cache_path.read_text())["NVDA|2026-03-14"] == r.json()["items"]


def test_news_failure_returns_error_source(monkeypatch, tmp_path):
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
    monkeypatch.setenv("BRIGHTDATA_ZONE", "z")
    monkeypatch.setattr(news, "CACHE_PATH", str(tmp_path / "cache.json"))
    monkeypatch.setattr(news.requests, "post", Mock(return_value=Mock(status_code=429)))
    r = client.get("/news", params={"symbol": "NVDA", "date": "2026-03-14"})
    assert r.status_code == 200
    assert r.json()["items"] == []
    assert r.json()["source"] == "error"
    assert "429" in r.json()["message"]
    assert "test-key" not in r.text

    monkeypatch.delenv("BRIGHTDATA_API_KEY", raising=False)
    r = client.get("/news", params={"symbol": "NVDA", "date": "2026-03-14"})
    assert r.status_code == 200
    assert r.json()["items"] == []
    assert r.json()["source"] == "error"


def test_engine_still_reads_news_cache(monkeypatch, tmp_path):
    import json as _json

    import engine

    cache_path = tmp_path / "cache.json"
    cache_path.write_text(_json.dumps({
        "NVDA|2026-03-14": [{"title": "cached", "source": "x", "published": "Mar 12, 2026"}],
    }))
    monkeypatch.setattr(news, "CACHE_PATH", str(cache_path))
    monkeypatch.setattr(news.requests, "post", lambda *a, **k: pytest.fail("engine must not hit the network"))
    assert engine._load_news_cache() == {
        "NVDA|2026-03-14": [{"title": "cached", "source": "x", "published": "Mar 12, 2026"}],
    }


def test_news_lowercase_symbol_normalized(monkeypatch):
    monkeypatch.setattr(main.news, "fetch_live_headlines", Mock(return_value=[]))
    r = client.get("/news", params={"symbol": "nvda", "date": "2026-03-14"})
    assert r.status_code == 200
    assert r.json()["symbol"] == "NVDA"


@pytest.mark.parametrize("symbol", ["", "NV DA", "../etc", "TOOLONGSYMBOL1", "nv$"])
def test_news_invalid_symbol_400(symbol):
    r = client.get("/news", params={"symbol": symbol, "date": "2026-03-14"})
    assert r.status_code == 400


@pytest.mark.parametrize("date", ["2026-13-01", "03/14/2026", "20260314", "2026-3-4", "x"])
def test_news_invalid_date_400(date):
    r = client.get("/news", params={"symbol": "NVDA", "date": date})
    assert r.status_code == 400


def test_news_missing_params_422_or_400():
    r = client.get("/news", params={"date": "2026-03-14"})
    assert r.status_code in (400, 422)


def test_news_rate_limit(monkeypatch):
    monkeypatch.setattr(main.news, "fetch_live_headlines", Mock(return_value=[]))
    t = [0.0]
    monkeypatch.setattr(main.time, "monotonic", lambda: t[0])

    for _ in range(9):
        assert client.get("/news", params={"symbol": "NVDA", "date": "2026-03-14"}).status_code == 200
    for _ in range(5):
        assert client.get("/news", params={"symbol": "nv$", "date": "2026-03-14"}).status_code == 400
    assert client.get("/news", params={"symbol": "NVDA", "date": "2026-03-14"}).status_code == 200
    assert client.get("/news", params={"symbol": "NVDA", "date": "2026-03-14"}).status_code == 429
    t[0] += 61
    assert client.get("/news", params={"symbol": "NVDA", "date": "2026-03-14"}).status_code == 200
