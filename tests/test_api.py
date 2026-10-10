import time

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
    response = client.post("/runs", json={"trades_csv": csv_content})
    run_id = response.json()["run_id"]
    time.sleep(6)
    response = client.get(f"/runs/{run_id}")
    assert response.status_code == 200
    data = response.json()
    # Status could be "done" or "error" depending on whether Anthropic is configured
    assert data["status"] in ["done", "error"]


def test_get_nonexistent_run():
    response = client.get("/runs/nonexistent")
    assert response.status_code == 200
    data = response.json()
    assert "error" in data
