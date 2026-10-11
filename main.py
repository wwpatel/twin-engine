import json
import os
import re
import threading
import tempfile
import time
import uuid
from collections import deque
from datetime import date as date_type
from typing import Dict, Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import engine
import insights
import activate
import news

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

runs: Dict[str, Dict[str, Any]] = {}

GURUS_DIR = "data/gurus"
guru_index: list[dict] = []
guru_public: dict[str, dict] = {}
guru_rules: dict[str, dict] = {}

NEWS_RATE_LIMIT = 10
NEWS_RATE_WINDOW_SECONDS = 60
_news_calls: deque = deque()
_news_lock = threading.Lock()
SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _read_json(path: str, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def load_gurus(gurus_dir: str | None = None) -> None:
    """Load precomputed gurus from disk; missing or unreadable files just leave the store empty."""
    gurus_dir = gurus_dir or GURUS_DIR
    index = _read_json(os.path.join(gurus_dir, "index.json"), [])

    guru_index.clear()
    guru_public.clear()
    guru_rules.clear()

    if not isinstance(index, list):
        return

    for entry in index:
        guru_index.append(entry)
        guru_id = entry.get("id")
        if not guru_id:
            continue
        public = _read_json(os.path.join(gurus_dir, f"{guru_id}.json"), None)
        if public is not None:
            guru_public[guru_id] = public
        rules = _read_json(os.path.join(gurus_dir, f"{guru_id}.rules.json"), None)
        if rules is not None:
            guru_rules[guru_id] = rules


def best_holdout_match(public: dict) -> float | None:
    matches = [
        h["holdout_match"]
        for h in public.get("hypotheses", [])
        if h.get("status") == "kept" and h.get("holdout_match") is not None
    ]
    return max(matches) if matches else None


load_gurus()


class RunRequest(BaseModel):
    dataset: str | None = None
    trades_csv: str | None = None


class RunResponse(BaseModel):
    run_id: str


class ActivateRequest(BaseModel):
    run_id: str | None = None
    guru_id: str | None = None
    insight_id: str
    dataset: str


RUN_TIMEOUT_SECONDS = 150


class RunTimedOut(Exception):
    pass


def _error_record(run_id: str, message: str) -> dict:
    # Keep whatever progress was made (hypotheses so far) alongside the error
    return {**runs.get(run_id, {}), "status": "error", "run_id": run_id, "message": message, "error": message}


def run_job(run_id: str, request: RunRequest):
    """Run discovery in the background. The stored record always has status running, done or error."""
    runs[run_id] = {"status": "running", "run_id": run_id}
    timed_out = threading.Event()
    outcome: dict = {}

    def work():
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
                if timed_out.is_set():
                    raise RunTimedOut()  # stops an abandoned run at its next round
                # Merge into the record so run_id and status survive progress updates
                runs[run_id] = {**runs[run_id], **update, "status": "running", "run_id": run_id}

            result = engine.run_discovery(csv_path, on_progress)
            # Build insights from the result
            result["insights"] = insights.build_insights(result)
            outcome["result"] = result
        except BaseException as e:
            outcome["error"] = e

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    worker.join(RUN_TIMEOUT_SECONDS)

    if worker.is_alive():
        timed_out.set()
        runs[run_id] = _error_record(run_id, f"Run timed out after {RUN_TIMEOUT_SECONDS} seconds")
    elif "error" in outcome:
        e = outcome["error"]
        runs[run_id] = _error_record(run_id, f"{type(e).__name__}: {e}")
    else:
        result = outcome["result"]
        result["run_id"] = run_id  # the id the client polls with, not the engine's internal one
        result["status"] = "done"
        runs[run_id] = result


@app.post("/runs", response_model=RunResponse)
def create_run(request: RunRequest):
    run_id = str(uuid.uuid4())
    thread = threading.Thread(target=run_job, args=(run_id, request))
    thread.start()
    return RunResponse(run_id=run_id)


@app.get("/runs/{run_id}")
def get_run(run_id: str):
    run = runs.get(run_id)
    if run is None:
        return {"error": "Run not found"}
    return {k: v for k, v in run.items() if k != "rule_codes"}


@app.get("/gurus")
def list_gurus():
    out = []
    for entry in guru_index:
        public = guru_public.get(entry.get("id"), {})
        out.append({
            "id": entry.get("id"),
            "name": entry.get("name"),
            "style": entry.get("style"),
            "bio": entry.get("bio"),
            "n_insights": len(public.get("insights", [])),
            "holdout_match": best_holdout_match(public),
        })
    return out


@app.get("/gurus/{guru_id}")
def get_guru(guru_id: str):
    if guru_id not in guru_public:
        raise HTTPException(status_code=404, detail="Guru not found")
    return guru_public[guru_id]


@app.post("/activate")
def activate_insight(request: ActivateRequest):
    if (request.run_id is None) == (request.guru_id is None):
        raise HTTPException(status_code=400, detail="Provide exactly one of run_id or guru_id")
    try:
        if request.run_id is not None:
            return activate.activate(runs, request.run_id, request.insight_id, request.dataset)
        return activate.activate_guru(guru_public, guru_rules, request.guru_id, request.insight_id, request.dataset)
    except activate.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _allow_news_call() -> bool:
    now = time.monotonic()
    with _news_lock:
        while _news_calls and now - _news_calls[0] >= NEWS_RATE_WINDOW_SECONDS:
            _news_calls.popleft()
        if len(_news_calls) >= NEWS_RATE_LIMIT:
            return False
        _news_calls.append(now)
        return True


@app.get("/news")
def get_news(symbol: str, date: str):
    symbol = symbol.strip().upper()
    if not SYMBOL_RE.match(symbol):
        raise HTTPException(status_code=400, detail="Invalid symbol")
    if not DATE_RE.match(date):
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    try:
        date_type.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")

    if not _allow_news_call():
        raise HTTPException(status_code=429, detail="News rate limit exceeded (10 per minute)")

    items = news.get_headlines(symbol, date)
    return {"symbol": symbol, "date": date, "items": items, "source": "live"}


@app.get("/health")
def health():
    return {"ok": True}
