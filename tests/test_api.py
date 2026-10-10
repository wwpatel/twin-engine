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
    response = client.post("/runs", json={"dataset": "sample"})
    run_id = response.json()["run_id"]
    time.sleep(6)
    response = client.get(f"/runs/{run_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "done"
    assert data["round"] == 5


def test_get_nonexistent_run():
    response = client.get("/runs/nonexistent")
    assert response.status_code == 200
    data = response.json()
    assert "error" in data
