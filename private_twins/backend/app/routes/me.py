"""Authenticated private portfolio and conversation APIs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.models import ConversationCreateRequest, ConversationMessageRequest, CreatorPublicationRequest
from app.services.answer_store import answer_store
from app.services.auth import optional_user_id, require_user_id
from app.services.creator_registry import get_twin
from app.services.repository import repository
from app.services.twin_chat import DISCLAIM, private_data_reply, request_llm_answer, select_evidence

router = APIRouter(prefix="/me", tags=["private user data"])


def _owner(user_id: str | None = Depends(optional_user_id)) -> str:
    return require_user_id(user_id)


def _portfolio_context(portfolio: dict) -> dict:
    """Pass only derived analysis into a private chat comparison, never raw CSV rows."""
    analysis = portfolio["analysis"]
    return {
        "source": "the user’s private uploaded-trade analysis",
        "summary": analysis.get("summary", {}),
        "patterns": [
            {"title": item.get("title"), "statement": item.get("statement"), "sample_size": item.get("sample_size")}
            for item in analysis.get("patterns", [])
        ],
        "warnings": analysis.get("warnings", []),
    }


def _public_twin_from_portfolio(request: CreatorPublicationRequest, portfolio: dict) -> dict:
    """Publish only derived pattern evidence after the creator explicitly opts in."""
    analysis = portfolio["analysis"]
    patterns = []
    for index, item in enumerate(analysis.get("patterns", []), start=1):
        patterns.append(
            {
                "id": f"published-pattern-{index}",
                "description": item.get("statement") or item.get("description") or item.get("title", "Observed pattern"),
                "sample_size": item.get("sample_size") or 0,
                "limitations": item.get("limitations") or ["Derived from creator-approved uploaded history."],
            }
        )
    if not patterns:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The latest analysis has no publishable patterns yet.")
    initials = "".join(part[0] for part in request.display_name.split()[:2]).upper() or "AI"
    return {
        "id": request.public_id,
        "display_name": request.display_name,
        "bio": request.bio,
        "style_summary": "Creator-approved historical patterns derived from uploaded trade analysis.",
        "public_identity": f"I am {request.display_name}'s AI Twin, based on creator-approved historical trade patterns.",
        "public_experience": "I can explain published historical patterns, not the creator’s private intentions or future decisions.",
        "communication_style": request.communication_style,
        "voice_examples": "I can explain what the published history shows and where it is uncertain.",
        "public_profile": {
            "headline": "Creator-approved historical trading playbook",
            "traits": ["evidence-backed", "creator-approved", "historical"],
            "expertise": ["published trade patterns", "historical evidence", "pattern limitations"],
            "conversation_starters": ["What patterns are published here?", "What evidence supports this insight?"],
        },
        "avatar": {"initials": initials, "accent": "#A3E635", "style": "original AI Twin avatar; not a portrait of the creator"},
        "opening_message": request.opening_message,
        "playbook": {
            "entry_approach": "See published evidence cards.",
            "exit_approach": "See published evidence cards.",
            "risk_posture": "Historical observations only; not financial advice.",
        },
        "recent_demo_activity": [],
        "patterns": patterns,
        "limitations": [
            "Only creator-approved derived historical patterns are public.",
            "Raw trades, private conversations, and personal analysis remain private.",
            "Historical behavior does not predict future decisions.",
            "This AI Twin is not the creator and does not provide financial advice.",
        ],
    }


@router.get("/portfolios/latest")
def latest_portfolio(user_id: str = Depends(_owner)) -> dict:
    portfolio = repository.latest_portfolio(user_id)
    if not portfolio:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No completed private analysis is available for this user.")
    return portfolio


@router.post("/creator-twin", status_code=status.HTTP_201_CREATED)
def publish_creator_twin(request: CreatorPublicationRequest, user_id: str = Depends(_owner)) -> dict:
    if not request.explicit_publication_consent:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Explicit publication consent is required.")
    if get_twin(request.public_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Choose a different public Twin ID.")
    portfolio = repository.latest_portfolio(user_id)
    if not portfolio:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Complete a private trade analysis before publishing a Twin.")
    profile = _public_twin_from_portfolio(request, portfolio)
    return repository.publish_twin(user_id, request.public_id, profile)


@router.post("/conversations", status_code=status.HTTP_201_CREATED)
def create_conversation(request: ConversationCreateRequest, user_id: str = Depends(_owner)) -> dict:
    if not get_twin(request.twin_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Public Twin not found.")
    return repository.create_conversation(user_id, request.twin_id, request.title)


@router.get("/conversations")
def conversations(user_id: str = Depends(_owner)) -> dict:
    return {"conversations": repository.list_conversations(user_id)}


@router.get("/conversations/{conversation_id}")
def conversation(conversation_id: str, user_id: str = Depends(_owner)) -> dict:
    result = repository.conversation(user_id, conversation_id)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")
    return result


@router.post("/conversations/{conversation_id}/messages")
def send_message(conversation_id: str, request: ConversationMessageRequest, user_id: str = Depends(_owner)) -> dict:
    conversation = repository.conversation(user_id, conversation_id)
    if not conversation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")
    twin = get_twin(conversation["twin_id"])
    if not twin:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Public Twin not found.")

    portfolio = repository.latest_portfolio(user_id) if request.include_my_portfolio else None
    if request.include_my_portfolio and not portfolio:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Upload and complete a private trade analysis before sharing it in this conversation.")
    evidence = select_evidence(request.message, twin["patterns"])
    context = _portfolio_context(portfolio) if portfolio else None
    # A public Twin still cannot access a private upload unless this signed-in user opted in.
    privacy_answer = private_data_reply(request.message) if not context else None
    if privacy_answer:
        answer, evidence = privacy_answer, []
    else:
        try:
            answer = request_llm_answer(twin, evidence, request.message, context)
        except RuntimeError as exc:
            detail = str(exc)
            code = status.HTTP_503_SERVICE_UNAVAILABLE if "not configured" in detail else status.HTTP_502_BAD_GATEWAY
            raise HTTPException(status_code=code, detail=detail) from exc

    user_message = repository.add_message(conversation_id, "user", request.message)
    answer_id = answer_store.put(twin["id"], answer)
    response_evidence = [
        {"pattern_id": item["id"], "description": item["description"], "sample_size": item["sample_size"]}
        for item in evidence
    ]
    assistant_message = repository.add_message(conversation_id, "assistant", answer, answer_id, response_evidence)
    return {
        "conversation_id": conversation_id,
        "user_message": user_message,
        "assistant_message": assistant_message,
        "portfolio_context_used": bool(context),
        "limitations": twin["limitations"],
        "disclaimer": DISCLAIM,
    }
