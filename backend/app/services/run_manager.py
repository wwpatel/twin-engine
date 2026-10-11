from __future__ import annotations

from copy import deepcopy
from threading import Lock
from time import sleep
from uuid import uuid4

from app.services.analysis import Trade, analyze
from app.services.repository import repository


class RunManager:
    """Small, process-local run store for the hackathon MVP."""

    def __init__(self) -> None:
        self._runs: dict[str, dict] = {}
        self._lock = Lock()

    def create(self, owner_user_id: str | None = None) -> dict:
        run_id = str(uuid4())
        run = {
            "run_id": run_id,
            "status": "queued",
            "progress": 0,
            "current_stage": "queued",
            "result": None,
            "error": None,
            "owner_user_id": owner_user_id,
        }
        with self._lock:
            self._runs[run_id] = run
        return deepcopy(run)

    def get(self, run_id: str) -> dict | None:
        with self._lock:
            run = self._runs.get(run_id)
            return deepcopy(run) if run else None

    def _update(self, run_id: str, **changes: object) -> None:
        with self._lock:
            if run_id in self._runs:
                self._runs[run_id].update(changes)

    def process(self, run_id: str, trades: list[Trade]) -> None:
        """Run deterministic analysis outside the POST request lifecycle."""
        try:
            self._update(run_id, status="running", progress=25, current_stage="matching_lots")
            sleep(0.03)
            self._update(run_id, progress=70, current_stage="discovering_patterns")
            result = analyze(trades)
            run = self.get(run_id)
            if run and run.get("owner_user_id"):
                repository.save_analysis(str(run["owner_user_id"]), run_id, result)
            self._update(
                run_id,
                status="completed",
                progress=100,
                current_stage="complete",
                result=result,
            )
        except Exception as exc:  # Defensive: background failures must be visible to clients.
            self._update(
                run_id,
                status="failed",
                progress=100,
                current_stage="failed",
                error=f"Analysis failed: {exc}",
            )


run_manager = RunManager()
