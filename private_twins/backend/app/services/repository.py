"""Small SQLite repository for private portfolios and user-owned conversations."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from threading import Lock
from uuid import uuid4

from app.config import database_path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Repository:
    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = Lock()
        self._initialize()

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS portfolios (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    run_id TEXT UNIQUE NOT NULL,
                    analysis_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    twin_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    answer_id TEXT,
                    evidence_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id)
                );
                CREATE TABLE IF NOT EXISTS public_twins (
                    twin_id TEXT PRIMARY KEY,
                    owner_user_id TEXT NOT NULL,
                    profile_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def create_portfolio(self, user_id: str, run_id: str) -> None:
        now = _now()
        with self._lock, self._connection() as connection:
            connection.execute(
                "INSERT INTO portfolios (id, user_id, run_id, analysis_json, created_at, updated_at) VALUES (?, ?, ?, NULL, ?, ?)",
                (str(uuid4()), user_id, run_id, now, now),
            )

    def save_analysis(self, user_id: str, run_id: str, analysis: dict) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                "UPDATE portfolios SET analysis_json = ?, updated_at = ? WHERE user_id = ? AND run_id = ?",
                (json.dumps(analysis), _now(), user_id, run_id),
            )

    def latest_portfolio(self, user_id: str) -> dict | None:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT run_id, analysis_json, created_at, updated_at FROM portfolios WHERE user_id = ? AND analysis_json IS NOT NULL ORDER BY updated_at DESC LIMIT 1",
                (user_id,),
            ).fetchone()
        if not row:
            return None
        return {"run_id": row["run_id"], "analysis": json.loads(row["analysis_json"]), "created_at": row["created_at"], "updated_at": row["updated_at"]}

    def create_conversation(self, user_id: str, twin_id: str, title: str) -> dict:
        conversation_id, now = str(uuid4()), _now()
        with self._lock, self._connection() as connection:
            connection.execute(
                "INSERT INTO conversations (id, user_id, twin_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (conversation_id, user_id, twin_id, title, now, now),
            )
        return {"id": conversation_id, "twin_id": twin_id, "title": title, "created_at": now, "updated_at": now}

    def list_conversations(self, user_id: str) -> list[dict]:
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT id, twin_id, title, created_at, updated_at FROM conversations WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def conversation(self, user_id: str, conversation_id: str) -> dict | None:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT id, twin_id, title, created_at, updated_at FROM conversations WHERE id = ? AND user_id = ?",
                (conversation_id, user_id),
            ).fetchone()
            if not row:
                return None
            messages = connection.execute(
                "SELECT id, role, content, answer_id, evidence_json, created_at FROM messages WHERE conversation_id = ? ORDER BY created_at",
                (conversation_id,),
            ).fetchall()
        item = dict(row)
        item["messages"] = [
            {**dict(message), "evidence": json.loads(message["evidence_json"]) if message["evidence_json"] else []}
            for message in messages
        ]
        for message in item["messages"]:
            message.pop("evidence_json", None)
        return item

    def add_message(self, conversation_id: str, role: str, content: str, answer_id: str | None = None, evidence: list[dict] | None = None) -> dict:
        message_id, now = str(uuid4()), _now()
        with self._lock, self._connection() as connection:
            connection.execute(
                "INSERT INTO messages (id, conversation_id, role, content, answer_id, evidence_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (message_id, conversation_id, role, content, answer_id, json.dumps(evidence or []), now),
            )
            connection.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
        return {"id": message_id, "role": role, "content": content, "answer_id": answer_id, "evidence": evidence or [], "created_at": now}

    def publish_twin(self, user_id: str, twin_id: str, profile: dict) -> dict:
        now = _now()
        with self._lock, self._connection() as connection:
            existing = connection.execute("SELECT owner_user_id FROM public_twins WHERE twin_id = ?", (twin_id,)).fetchone()
            if existing and existing["owner_user_id"] != user_id:
                raise ValueError("That public Twin ID is already owned by another creator.")
            connection.execute(
                "INSERT INTO public_twins (twin_id, owner_user_id, profile_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(twin_id) DO UPDATE SET profile_json = excluded.profile_json, updated_at = excluded.updated_at",
                (twin_id, user_id, json.dumps(profile), now, now),
            )
        return profile

    def public_twin(self, twin_id: str) -> dict | None:
        with self._lock, self._connection() as connection:
            row = connection.execute("SELECT profile_json FROM public_twins WHERE twin_id = ?", (twin_id,)).fetchone()
        return json.loads(row["profile_json"]) if row else None

    def public_twins(self) -> list[dict]:
        with self._lock, self._connection() as connection:
            rows = connection.execute("SELECT profile_json FROM public_twins ORDER BY updated_at DESC").fetchall()
        return [json.loads(row["profile_json"]) for row in rows]

    def delete_public_twin(self, twin_id: str) -> None:
        """Test cleanup helper; production deletion will require an owner-authorized route."""
        with self._lock, self._connection() as connection:
            connection.execute("DELETE FROM public_twins WHERE twin_id = ?", (twin_id,))


repository = Repository(database_path())
