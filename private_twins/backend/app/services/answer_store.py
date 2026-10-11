from __future__ import annotations

from threading import Lock
from time import monotonic
from uuid import uuid4


class AnswerStore:
    """Short-lived answer records authorize speech without accepting arbitrary text."""

    def __init__(self) -> None:
        self._answers: dict[str, dict] = {}
        self._lock = Lock()

    def put(self, twin_id: str, text: str) -> str:
        answer_id = str(uuid4())
        with self._lock:
            self._answers[answer_id] = {"twin_id": twin_id, "text": text, "created": monotonic()}
        return answer_id

    def get(self, answer_id: str, twin_id: str) -> str | None:
        with self._lock:
            answer = self._answers.get(answer_id)
            if not answer or answer["twin_id"] != twin_id or monotonic() - answer["created"] > 600:
                return None
            return answer["text"]


answer_store = AnswerStore()

