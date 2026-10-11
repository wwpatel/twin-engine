from typing import Any, Literal

from pydantic import BaseModel, Field


RunStatus = Literal["queued", "running", "completed", "failed"]


class RunCreated(BaseModel):
    run_id: str
    status: Literal["queued"]
    progress: int


class RunResponse(BaseModel):
    run_id: str
    status: RunStatus
    progress: int
    current_stage: str
    result: dict[str, Any] | None
    error: str | None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)


class ChatResponse(BaseModel):
    twin_id: str
    answer: str
    answer_id: str
    evidence: list[dict[str, object]]
    limitations: list[str]
    disclaimer: str


class SpeakRequest(BaseModel):
    answer_id: str = Field(min_length=1, max_length=100)


class ConversationCreateRequest(BaseModel):
    twin_id: str = Field(min_length=1, max_length=100)
    title: str = Field(default="New conversation", min_length=1, max_length=120)


class ConversationMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    include_my_portfolio: bool = False


class CreatorPublicationRequest(BaseModel):
    public_id: str = Field(min_length=3, max_length=60, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    display_name: str = Field(min_length=2, max_length=80)
    bio: str = Field(min_length=10, max_length=240)
    communication_style: str = Field(min_length=10, max_length=240)
    opening_message: str = Field(min_length=10, max_length=240)
    explicit_publication_consent: bool
