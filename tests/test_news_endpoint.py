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
    monkeypatch.setattr(main.news, "get_headlines", mock)
    r = client.get("/news", params={"symbol": "NVDA", "date": "2026-03-14"})
    assert r.status_code == 200
    assert r.json() == {"symbol": "NVDA", "date": "2026-03-14", "items": ITEMS, "source": "live"}
    mock.assert_called_once_with("NVDA", "2026-03-14")


def test_news_calls_bright_data_not_just_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
    monkeypatch.setenv("BRIGHTDATA_ZONE", "z")
    monkeypatch.setattr(news, "CACHE_PATH", str(tmp_path / "cache.json"))
    post = Mock(return_value=Mock(status_code=200, json=lambda: {
        "organic": [{"title": "t", "source": "s", "date": "p"}],
    }))
    monkeypatch.setattr(news.requests, "post", post)
    r = client.get("/news", params={"symbol": "NVDA", "date": "2026-03-14"})
    assert r.status_code == 200
    assert r.json()["items"] == [{"title": "t", "source": "s", "published": "p"}]
    post.assert_called_once()
    _, kwargs = post.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer test-key"
    assert kwargs["json"]["zone"] == "z"
    assert "test-key" not in r.text


def test_news_lowercase_symbol_normalized(monkeypatch):
    monkeypatch.setattr(main.news, "get_headlines", Mock(return_value=[]))
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
    monkeypatch.setattr(main.news, "get_headlines", Mock(return_value=[]))
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
