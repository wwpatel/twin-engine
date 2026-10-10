import pytest


@pytest.fixture(autouse=True)
def _no_api_keys(monkeypatch):
    """Tests must behave the same on a dev machine and in CI, so never see real credentials."""
    for name in ("DAYTONA_API_KEY", "ANTHROPIC_API_KEY", "BRIGHTDATA_API_KEY"):
        monkeypatch.delenv(name, raising=False)
