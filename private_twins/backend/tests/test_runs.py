from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
VALID_CSV = b"date,symbol,side,qty,price\n2025-01-02,AAPL,buy,3,190.50\n"


def upload(content: bytes = VALID_CSV, filename: str = "trades.csv"):
    return client.post("/runs", files={"file": (filename, content, "text/csv")})


def test_valid_csv_creates_completed_run_with_contract() -> None:
    created = upload()
    assert created.status_code == 202
    assert created.json()["status"] == "queued"
    result = client.get(f"/runs/{created.json()['run_id']}")
    assert result.status_code == 200
    body = result.json()
    assert body["status"] == "completed"
    assert body["progress"] == 100
    assert body["current_stage"] == "complete"
    assert set(body) == {"run_id", "status", "progress", "current_stage", "result", "error"}
    assert {"summary", "hypotheses", "patterns", "exceptions", "news_context", "warnings"} <= set(body["result"])
    assert body["result"]["warnings"]
    assert body["error"] is None


def test_unknown_run_is_404() -> None:
    assert client.get("/runs/not-a-run").status_code == 404


def test_missing_file_is_rejected() -> None:
    assert client.post("/runs").status_code == 422


def test_empty_file_is_rejected() -> None:
    assert upload(b"").status_code == 400


def test_non_csv_filename_is_rejected() -> None:
    assert upload(VALID_CSV, "trades.txt").status_code == 400


def test_missing_columns_are_rejected() -> None:
    assert upload(b"date,symbol\n2025-01-02,AAPL\n").status_code == 400


def test_invalid_date_is_rejected() -> None:
    assert upload(b"date,symbol,side,qty,price\nnot-a-date,AAPL,BUY,1,1\n").status_code == 400


def test_invalid_side_is_rejected() -> None:
    assert upload(b"date,symbol,side,qty,price\n2025-01-02,AAPL,HOLD,1,1\n").status_code == 400


def test_invalid_quantity_and_price_are_rejected() -> None:
    assert upload(b"date,symbol,side,qty,price\n2025-01-02,AAPL,BUY,0,-1\n").status_code == 400


def test_oversized_upload_is_rejected() -> None:
    assert upload(b"x" * (5 * 1024 * 1024 + 1)).status_code == 413


def test_concurrent_runs_are_distinct() -> None:
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: upload(), range(4)))
    ids = {response.json()["run_id"] for response in responses}
    assert len(ids) == 4
    assert all(client.get(f"/runs/{run_id}").status_code == 200 for run_id in ids)


def test_demo_csv_completes_with_real_patterns() -> None:
    demo = (Path(__file__).parents[1] / "examples" / "demo_trades.csv").read_bytes()
    created = upload(demo, "demo_trades.csv")
    body = client.get(f"/runs/{created.json()['run_id']}").json()
    assert body["status"] == "completed"
    assert body["result"]["summary"]["realized_pnl"] == 358.0
    assert {pattern["id"] for pattern in body["result"]["patterns"]} >= {"holding_duration", "preferred_symbol"}
