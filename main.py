import json
import threading
import time
import uuid
from typing import Dict, Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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


def load_contract_example() -> Dict[str, Any]:
    with open("contract.example.json") as f:
        return json.load(f)


def run_job(run_id: str, request: RunRequest):
    contract = load_contract_example()
    contract["run_id"] = run_id
    contract["status"] = "running"
    runs[run_id] = contract

    for round_num in range(1, 6):
        contract["round"] = round_num
        runs[run_id] = contract.copy()
        time.sleep(1)

    contract["status"] = "done"
    runs[run_id] = contract


@app.post("/runs", response_model=RunResponse)
def create_run(request: RunRequest):
    run_id = str(uuid.uuid4())
    thread = threading.Thread(target=run_job, args=(run_id, request))
    thread.start()
    return RunResponse(run_id=run_id)


@app.get("/runs/{run_id}")
def get_run(run_id: str):
    return runs.get(run_id, {"error": "Run not found"})
