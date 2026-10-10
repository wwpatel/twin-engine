import pytest


@pytest.fixture(autouse=True)
def _no_api_keys(monkeypatch):
    """Tests must behave the same on a dev machine and in CI, so never see real credentials."""
    for name in ("DAYTONA_API_KEY", "ANTHROPIC_API_KEY", "BRIGHTDATA_API_KEY"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _isolated_news_cache(monkeypatch, tmp_path):
    """Never read a developer's local data/news_cache.json; tests that need a cache set their own."""
    monkeypatch.setattr("news.CACHE_PATH", str(tmp_path / "no_news_cache.json"))
