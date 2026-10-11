from __future__ import annotations

import csv
import io
import math
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status

from app.models import RunCreated, RunResponse
from app.services.analysis import Trade
from app.services.auth import optional_user_id
from app.services.repository import repository
from app.services.run_manager import run_manager

router = APIRouter(prefix="/runs", tags=["runs"])

MAX_FILE_SIZE = 5 * 1024 * 1024
REQUIRED_COLUMNS = {"date", "symbol", "side", "qty", "price"}


def _bad_request(detail: str) -> None:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _parse_date(value: str, row_number: int) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed
    except (TypeError, ValueError):
        _bad_request(f"Row {row_number}: date must be a valid ISO-8601 date or datetime.")


def _positive_number(value: str | None, field: str, row_number: int) -> float:
    try:
        number = float(value or "")
    except (TypeError, ValueError):
        _bad_request(f"Row {row_number}: {field} must be a positive number.")
    if not math.isfinite(number) or number <= 0:
        _bad_request(f"Row {row_number}: {field} must be a positive number.")
    return number


def validate_csv(content: bytes) -> list[Trade]:
    if not content:
        _bad_request("Uploaded CSV file is empty.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        _bad_request("CSV must be UTF-8 encoded.")

    try:
        reader = csv.DictReader(io.StringIO(text), strict=True)
        headers = set(reader.fieldnames or [])
    except csv.Error as exc:
        _bad_request(f"Malformed CSV: {exc}")
    missing = REQUIRED_COLUMNS - headers
    if missing:
        _bad_request("CSV is missing required columns: " + ", ".join(sorted(missing)))
    trades: list[Trade] = []
    try:
        for row_number, row in enumerate(reader, start=2):
            if not row or None in row:
                _bad_request(f"Row {row_number}: malformed CSV row.")
            date = _parse_date(row.get("date", ""), row_number)
            symbol = (row.get("symbol") or "").strip().upper()
            if not symbol:
                _bad_request(f"Row {row_number}: symbol is required.")
            side = (row.get("side") or "").strip().upper()
            if side not in {"BUY", "SELL"}:
                _bad_request(f"Row {row_number}: side must be BUY or SELL.")
            trades.append(Trade(
                trade_id=f"T{row_number - 1:03d}",
                date=date,
                symbol=symbol,
                side=side,
                qty=_positive_number(row.get("qty"), "qty", row_number),
                price=_positive_number(row.get("price"), "price", row_number),
                source_index=row_number - 1,
            ))
    except csv.Error as exc:
        _bad_request(f"Malformed CSV: {exc}")
    if not trades:
        _bad_request("CSV must contain at least one trade row.")
    return sorted(trades, key=lambda item: (item.date, item.source_index))


@router.post("", response_model=RunCreated, status_code=status.HTTP_202_ACCEPTED)
async def create_run(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user_id: str | None = Depends(optional_user_id),
) -> dict:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        _bad_request("Uploaded file must have a .csv extension.")
    content = await file.read(MAX_FILE_SIZE + 1)
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="CSV exceeds the 5 MB limit.")
    trades = validate_csv(content)
    run = run_manager.create(user_id)
    if user_id:
        repository.create_portfolio(user_id, run["run_id"])
    background_tasks.add_task(run_manager.process, run["run_id"], trades)
    return {"run_id": run["run_id"], "status": "queued", "progress": 0}


@router.get("/{run_id}", response_model=RunResponse)
def get_run(run_id: str) -> dict:
    run = run_manager.get(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")
    return run
