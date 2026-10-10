import time
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_create_run():
    response = client.post("/runs", json={"dataset": "sample"})
    assert response.status_code == 200
    data = response.json()
    assert "run_id" in data


def test_get_run():
    # Use trades_csv instead of dataset to avoid missing sample_trades.csv
    csv_content = """date,symbol,side,qty,price
2025-01-02,AAPL,buy,10,150.0
2025-01-03,AAPL,sell,10,155.0
"""
    with patch("engine.run_discovery") as mock_discovery:
        mock_discovery.return_value = {
            "run_id": "test-run-id",
            "status": "done",
            "round": 1,
            "hypotheses": [],
            "baseline": {"text": "baseline", "holdout_match": None},
            "exceptions": [],
            "summary": {"followed_pct": 0.0, "return_when_followed": None, "return_when_broken": None},
        }
        response = client.post("/runs", json={"trades_csv": csv_content})
        run_id = response.json()["run_id"]
        time.sleep(1)
        response = client.get(f"/runs/{run_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "done"


def test_get_nonexistent_run():
    response = client.get("/runs/nonexistent")
    assert response.status_code == 200
    data = response.json()
    assert "error" in data
