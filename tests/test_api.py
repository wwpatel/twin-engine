import time

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_create_run():
    response = client.post("/runs", json={"dataset": "sample"})
    assert response.status_code == 200
    data = response.json()
    assert "run_id" in data


def test_get_run(monkeypatch):
    # Mock the engine so the test never touches the network, Anthropic, or Daytona
    monkeypatch.setattr(
        "main.engine.run_discovery",
        lambda csv_path, on_progress: {"run_id": "mock", "status": "done"},
    )
    csv_content = """date,symbol,side,qty,price
2025-01-02,AAPL,buy,10,150.0
2025-01-03,AAPL,sell,10,155.0
"""
    response = client.post("/runs", json={"trades_csv": csv_content})
    run_id = response.json()["run_id"]
    for _ in range(50):
        data = client.get(f"/runs/{run_id}").json()
        if data.get("status") == "done":
            break
        time.sleep(0.1)
    assert data["status"] == "done"
    assert data["run_id"] == "mock"


def test_get_nonexistent_run():
    response = client.get("/runs/nonexistent")
    assert response.status_code == 200
    data = response.json()
    assert "error" in data
