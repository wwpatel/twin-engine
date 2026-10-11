from fastapi.testclient import TestClient

from app.main import app
from app.services.creator_registry import get_twin
from app.services.twin_chat import _system_prompt

client = TestClient(app)


def test_chat_requires_configured_provider(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    response = client.post("/twins/alex-demo/chat", json={"message": "What is the holding period?"})
    assert response.status_code == 503
    assert "OPENAI_API_KEY" in response.json()["detail"]


def test_chat_returns_only_registry_evidence_and_answer_id(monkeypatch) -> None:
    monkeypatch.setattr("app.routes.twins.request_llm_answer", lambda twin, evidence, message: "The published demo evidence shows three days.")
    response = client.post("/twins/alex-demo/chat", json={"message": "What is the typical holding period?"})
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "The published demo evidence shows three days."
    assert body["evidence"][0]["pattern_id"] == "holding_duration"
    assert body["answer_id"]
    assert "not the real trader" in body["disclaimer"]


def test_unknown_twin_is_not_found() -> None:
    assert client.post("/twins/not-real/chat", json={"message": "Hello"}).status_code == 404


def test_public_twin_cannot_access_a_users_private_uploaded_trades(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.routes.twins.request_llm_answer",
        lambda *args: (_ for _ in ()).throw(AssertionError("Private-data request must not reach the provider")),
    )
    response = client.post("/twins/alex-demo/chat", json={"message": "Can you see my uploaded CSV trades?"})
    assert response.status_code == 200
    body = response.json()
    assert "can’t access your private CSV" in body["answer"]
    assert body["evidence"] == []


def test_public_twin_profiles_are_available_without_private_run_data() -> None:
    listing = client.get("/twins")
    assert listing.status_code == 200
    assert len(listing.json()["twins"]) >= 6
    assert {"alex-demo", "maya-demo", "jack-demo", "lena-demo", "daniel-demo", "sofia-demo"}.issubset(
        {twin["id"] for twin in listing.json()["twins"]}
    )
    maya = client.get("/twins/maya-demo")
    assert maya.status_code == 200
    body = maya.json()
    assert body["public_profile"]["traits"] == ["focused", "energetic", "measured"]
    assert body["playbook"]["entry_approach"]
    assert body["opening_message"].startswith("Hey — Maya")
    assert body["recent_demo_activity"][0]["date"] == "2026-09-19"
    assert body["avatar"]["initials"] == "MR"
    assert "result" not in body


def test_each_demo_twin_has_an_approved_distinct_communication_style() -> None:
    maya = get_twin("maya-demo")
    jack = get_twin("jack-demo")
    assert maya and jack
    assert maya["communication_style"] != jack["communication_style"]
    assert maya["communication_style"] in _system_prompt(maya, maya["patterns"][:1])
    assert "Speak in first person" in _system_prompt(maya, maya["patterns"][:1])
    assert maya["voice_examples"] in _system_prompt(maya, maya["patterns"][:1])
    assert maya["playbook"]["entry_approach"] in _system_prompt(maya, maya["patterns"][:1])
    assert maya["recent_demo_activity"][0]["summary"] in _system_prompt(maya, maya["patterns"][:1])
    assert "Do not assign a strategy label" in _system_prompt(maya, maya["patterns"][:1])


def test_speak_only_accepts_a_previous_answer_for_the_same_twin(monkeypatch) -> None:
    monkeypatch.setattr("app.routes.twins.request_llm_answer", lambda twin, evidence, message: "Approved answer.")
    monkeypatch.setattr("app.routes.twins.synthesize", lambda text, twin_id: b"fake-mp3")
    answer_id = client.post("/twins/alex-demo/chat", json={"message": "Holding period?"}).json()["answer_id"]
    response = client.post("/twins/alex-demo/speak", json={"answer_id": answer_id})
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.content == b"fake-mp3"
    assert client.post("/twins/maya-demo/speak", json={"answer_id": answer_id}).status_code == 400


def test_speak_reports_unconfigured_fish_audio() -> None:
    response = client.post("/twins/alex-demo/speak", json={"answer_id": "not-a-real-answer"})
    assert response.status_code == 400
