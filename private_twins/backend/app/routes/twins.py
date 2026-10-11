from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response

from app.models import ChatRequest, ChatResponse, SpeakRequest
from app.services.answer_store import answer_store
from app.services.creator_registry import get_twin, list_twins
from app.services.fish_audio import synthesize
from app.services.twin_chat import DISCLAIM, private_data_reply, request_llm_answer, select_evidence

router = APIRouter(prefix="/twins", tags=["twins"])


def _twin_or_404(twin_id: str) -> dict:
    twin = get_twin(twin_id)
    if not twin:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Public demo Twin not found.")
    return twin


def _public_profile(twin: dict) -> dict:
    """A deliberately public payload for marketplace/profile UI; no private run data."""
    return {
        "id": twin["id"],
        "display_name": twin["display_name"],
        "bio": twin["bio"],
        "style_summary": twin["style_summary"],
        "public_identity": twin["public_identity"],
        "public_experience": twin["public_experience"],
        "public_profile": twin["public_profile"],
        "avatar": twin["avatar"],
        "playbook": twin["playbook"],
        "opening_message": twin["opening_message"],
        "recent_demo_activity": twin["recent_demo_activity"],
        "patterns": [
            {"id": item["id"], "description": item["description"], "sample_size": item["sample_size"], "limitations": item["limitations"]}
            for item in twin["patterns"]
        ],
        "limitations": twin["limitations"],
        "disclaimer": DISCLAIM,
    }


@router.get("")
def twins() -> dict:
    return {"twins": [_public_profile(twin) for twin in list_twins()]}


@router.get("/{twin_id}")
def twin_profile(twin_id: str) -> dict:
    return _public_profile(_twin_or_404(twin_id))


@router.post("/{twin_id}/chat", response_model=ChatResponse)
def chat(twin_id: str, request: ChatRequest) -> dict:
    twin = _twin_or_404(twin_id)
    privacy_answer = private_data_reply(request.message)
    evidence = [] if privacy_answer else select_evidence(request.message, twin["patterns"])
    if privacy_answer:
        answer = privacy_answer
    else:
        try:
            answer = request_llm_answer(twin, evidence, request.message)
        except RuntimeError as exc:
            detail = str(exc)
            code = status.HTTP_503_SERVICE_UNAVAILABLE if "not configured" in detail else status.HTTP_502_BAD_GATEWAY
            raise HTTPException(status_code=code, detail=detail) from exc
    answer_id = answer_store.put(twin_id, answer)
    return {
        "twin_id": twin_id,
        "answer": answer,
        "answer_id": answer_id,
        "evidence": [
            {"pattern_id": item["id"], "description": item["description"], "sample_size": item["sample_size"]}
            for item in evidence
        ],
        "limitations": twin["limitations"],
        "disclaimer": DISCLAIM,
    }


@router.post("/{twin_id}/speak")
def speak(twin_id: str, request: SpeakRequest) -> Response:
    _twin_or_404(twin_id)
    text = answer_store.get(request.answer_id, twin_id)
    if text is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="answer_id is invalid, expired, or belongs to another Twin.")
    try:
        audio = synthesize(text, twin_id)
    except RuntimeError as exc:
        detail = str(exc)
        code = status.HTTP_503_SERVICE_UNAVAILABLE if "not configured" in detail else status.HTTP_502_BAD_GATEWAY
        raise HTTPException(status_code=code, detail=detail) from exc
    return Response(content=audio, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})
