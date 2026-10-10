import json
import threading
import tempfile
import uuid
from typing import Dict, Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import engine

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

runs: Dict[str, Dict[str, Any]] = {}


class RunRequest(BaseModel):
    dataset: str | None = None
    trades_csv: str | None = None


class RunResponse(BaseModel):
    run_id: str


def run_job(run_id: str, request: RunRequest):
    # Determine CSV path
    if request.dataset == "sample":
        csv_path = "data/sample_trades.csv"
    elif request.trades_csv:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(request.trades_csv)
            csv_path = f.name
    else:
        runs[run_id] = {"status": "error", "error": "Must provide dataset='sample' or trades_csv"}
        return

    runs[run_id] = {"status": "running", "run_id": run_id}

    def on_progress(update: dict):
        runs[run_id] = update

    try:
        result = engine.run_discovery(csv_path, on_progress)
        runs[run_id] = result
    except Exception as e:
        runs[run_id] = {"status": "error", "error": str(e)}


@app.post("/runs", response_model=RunResponse)
def create_run(request: RunRequest):
    run_id = str(uuid.uuid4())
    thread = threading.Thread(target=run_job, args=(run_id, request))
    thread.start()
    return RunResponse(run_id=run_id)


@app.get("/runs/{run_id}")
def get_run(run_id: str):
    return runs.get(run_id, {"error": "Run not found"})
