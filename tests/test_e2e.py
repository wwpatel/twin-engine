import json
import tempfile
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import engine


@pytest.fixture
def sample_csv():
    """Tiny fixture CSV for testing when data/sample_trades.csv doesn't exist."""
    csv_content = """date,symbol,side,qty,price
2025-01-02,AAPL,buy,10,150.0
2025-01-03,AAPL,sell,10,155.0
2025-01-04,MSFT,buy,10,300.0
2025-01-05,MSFT,sell,10,310.0
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(csv_content)
        return f.name


@pytest.fixture
def mock_anthropic():
    """Mock Anthropic client."""
    with patch("engine._make_client") as mock:
        client = MagicMock()
        mock.return_value = client

        # Mock response that returns a simple rule
        response = MagicMock()
        response.content = [
            MagicMock(text="<description>Buy when price > 100</description>"),
            MagicMock(text="<code>\ndef rule(row):\n    if row.get(\"price\", 0) > 100:\n        return \"buy\"\n    return None\n</code>"),
        ]
        client.messages.create.return_value = response

        yield client


@pytest.fixture
def mock_news_cache():
    """Mock news cache."""
    cache_data = {
        "AAPL|2025-01-02": [
            {"title": "Apple announces new product", "source": "TechNews", "published": "2025-01-01"}
        ],
        "MSFT|2025-01-04": [
            {"title": "Microsoft earnings beat expectations", "source": "Finance", "published": "2025-01-03"}
        ],
    }
    with patch("news.get_headlines") as mock_news:
        mock_news.side_effect = lambda symbol, date: cache_data.get(
            f"{symbol}|{date}", []
        )
        yield mock_news


def test_e2e_response_shape(sample_csv, mock_anthropic, mock_news_cache):
    """End-to-end test with mocked Anthropic and sandbox, asserting response shape matches contract.example.json."""
    with open("contract.example.json") as f:
        contract = json.load(f)

    # Mock sandbox.run_rule (sandbox is imported inside run_discovery)
    with patch("sandbox.run_rule") as mock_sandbox:
        mock_sandbox.return_value = ["buy", None, "buy", None]

        progress_updates = []

        def on_progress(update):
            progress_updates.append(update)

        result = engine.run_discovery(sample_csv, on_progress)

        # Assert response shape matches contract
        assert "run_id" in result
        assert result["status"] in ["running", "done", "error"]
        assert "round" in result
        assert isinstance(result["round"], int)
        assert "hypotheses" in result
        assert isinstance(result["hypotheses"], list)
        assert "baseline" in result
        assert "exceptions" in result
        assert isinstance(result["exceptions"], list)
        assert "summary" in result

        # Check hypotheses structure
        if result["hypotheses"]:
            for h in result["hypotheses"]:
                assert "text" in h
                assert "status" in h
                assert h["status"] in ["kept", "rejected"]
                assert "reason" in h

        # Check baseline structure
        assert "text" in result["baseline"]
        assert "holdout_match" in result["baseline"]

        # Check exceptions structure
        for exc in result["exceptions"]:
            assert "date" in exc
            assert "symbol" in exc
            assert "side" in exc
            assert "broke_rule" in exc
            assert "context" in exc
            assert isinstance(exc["context"], list)
            assert "outcome_pct" in exc

        # Check summary structure
        assert "followed_pct" in result["summary"]
        assert "return_when_followed" in result["summary"]
        assert "return_when_broken" in result["summary"]

        # Check progress updates
        assert len(progress_updates) > 0
        for update in progress_updates:
            assert "round" in update
            assert "hypotheses" in update


def test_e2e_news_context_fallback(sample_csv, mock_anthropic):
    """Test that news context falls back to 'No clear cause in the news' when cache is empty."""
    with patch("news.get_headlines") as mock_news:
        # Return empty headlines (cache miss)
        mock_news.return_value = []

        # Mock sandbox.run_rule
        with patch("sandbox.run_rule") as mock_sandbox:
            mock_sandbox.return_value = ["buy", None, "buy", None]

            progress_updates = []

            def on_progress(update):
                progress_updates.append(update)

            result = engine.run_discovery(sample_csv, on_progress)

            # Check that exceptions have the fallback context
            for exc in result["exceptions"]:
                assert exc["context"] == ["No clear cause in the news"]
