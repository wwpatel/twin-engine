import pandas as pd
import pytest

from sandbox import SandboxError, run_rule


@pytest.fixture(autouse=True)
def reset_daytona_state():
    """Reset Daytona global state before each test."""
    import sandbox
    sandbox._daytona_sandbox = None
    sandbox._daytona_client = None
    yield
    sandbox._daytona_sandbox = None
    sandbox._daytona_client = None


def test_simple_rule():
    code = """
def rule(row):
    if row.get("price", 0) > 100:
        return "buy"
    elif row.get("price", 0) < 50:
        return "sell"
    return None
"""
    df = pd.DataFrame([{"price": 150}, {"price": 30}, {"price": 75}])
    result = run_rule(code, df)
    assert result == ["buy", "sell", None]


def test_rule_that_raises():
    code = """
def rule(row):
    raise ValueError("Test error")
"""
    df = pd.DataFrame([{"price": 100}])
    with pytest.raises(SandboxError, match="Rule execution failed"):
        run_rule(code, df)


def test_rule_that_sleeps_forever():
    code = """
import time

def rule(row):
    time.sleep(100)
    return "buy"
"""
    df = pd.DataFrame([{"price": 100}])
    with pytest.raises(SandboxError, match="timed out"):
        run_rule(code, df, timeout_s=1)


def test_daytona_not_used_without_api_key(monkeypatch):
    """Test that local subprocess is used when DAYTONA_API_KEY is not set."""
    code = """
def rule(row):
    return "buy" if row.get("price", 0) > 100 else None
"""
    df = pd.DataFrame([{"price": 150}, {"price": 50}])

    # Ensure no API key
    monkeypatch.delenv("DAYTONA_API_KEY", raising=False)

    result = run_rule(code, df)
    assert result == ["buy", None]
