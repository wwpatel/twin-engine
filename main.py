import json
import threading
import tempfile
import uuid
from typing import Dict, Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import engine
import insights
import activate

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


class ActivateRequest(BaseModel):
    run_id: str
    insight_id: str
    dataset: str


def run_job(run_id: str, request: RunRequest):
    """Run discovery in the background. The stored record always has status running, done or error."""
    runs[run_id] = {"status": "running", "run_id": run_id}

    try:
        # Determine CSV path
        if request.dataset == "sample":
            csv_path = "data/sample_trades.csv"
        elif request.trades_csv:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
                f.write(request.trades_csv)
                csv_path = f.name
        else:
            raise ValueError("Must provide dataset='sample' or trades_csv")

        def on_progress(update: dict):
            # Merge into the record so run_id and status survive progress updates
            runs[run_id] = {**runs[run_id], **update, "status": "running", "run_id": run_id}

        result = engine.run_discovery(csv_path, on_progress)
        # Build insights from the result
        result["insights"] = insights.build_insights(result)
        result["run_id"] = run_id  # the id the client polls with, not the engine's internal one
        result["status"] = "done"
        runs[run_id] = result
    except Exception as e:
        message = f"{type(e).__name__}: {e}"
        runs[run_id] = {
            **runs.get(run_id, {}),
            "status": "error",
            "run_id": run_id,
            "message": message,
            "error": message,
        }


@app.post("/runs", response_model=RunResponse)
def create_run(request: RunRequest):
    run_id = str(uuid.uuid4())
    thread = threading.Thread(target=run_job, args=(run_id, request))
    thread.start()
    return RunResponse(run_id=run_id)


@app.get("/runs/{run_id}")
def get_run(run_id: str):
    return runs.get(run_id, {"error": "Run not found"})


@app.post("/activate")
def activate_insight(request: ActivateRequest):
    try:
        result = activate.activate(runs, request.run_id, request.insight_id, request.dataset)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
