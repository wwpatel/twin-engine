from fastapi.testclient import TestClient
from uuid import uuid4

from app.main import app
from app.services.repository import repository

client = TestClient(app)
HEADERS = {"X-Dev-User-ID": "user_private_test"}


def test_private_endpoints_require_a_signed_in_owner() -> None:
    response = client.get("/me/conversations")
    assert response.status_code == 401


def test_user_owned_conversation_persists_messages_and_can_opt_in_to_derived_portfolio_context(monkeypatch) -> None:
    run_id = f"private-run-{uuid4()}"
    repository.create_portfolio("user_private_test", run_id)
    repository.save_analysis(
        "user_private_test",
        run_id,
        {
            "summary": {"total_trades": 12, "realized_pnl": 358.0},
            "patterns": [{"title": "Observed holding duration", "statement": "Three days", "sample_size": 6}],
            "warnings": ["Private test warning"],
        },
    )
    created = client.post("/me/conversations", headers=HEADERS, json={"twin_id": "maya-demo", "title": "Maya comparison"})
    assert created.status_code == 201
    conversation_id = created.json()["id"]

    def answer(twin, evidence, message, viewer_context):
        assert viewer_context["summary"]["total_trades"] == 12
        return "I can discuss the analysis summary you chose to share."

    monkeypatch.setattr("app.routes.me.request_llm_answer", answer)
    sent = client.post(
        f"/me/conversations/{conversation_id}/messages",
        headers=HEADERS,
        json={"message": "Compare my holding period with yours.", "include_my_portfolio": True},
    )
    assert sent.status_code == 200
    assert sent.json()["portfolio_context_used"] is True

    loaded = client.get(f"/me/conversations/{conversation_id}", headers=HEADERS)
    assert loaded.status_code == 200
    assert [message["role"] for message in loaded.json()["messages"]] == ["user", "assistant"]
    assert client.get(f"/me/conversations/{conversation_id}", headers={"X-Dev-User-ID": "another-user"}).status_code == 404


def test_creator_can_explicitly_publish_derived_patterns_without_raw_trade_data() -> None:
    public_id = f"creator-{uuid4().hex[:12]}"
    try:
        response = client.post(
            "/me/creator-twin",
            headers=HEADERS,
            json={
                "public_id": public_id,
                "display_name": "Test Creator",
                "bio": "Creator-approved public historical trading patterns.",
                "communication_style": "Warm, careful, and evidence-first.",
                "opening_message": "Hey — I can explain the patterns I chose to publish.",
                "explicit_publication_consent": True,
            },
        )
        assert response.status_code == 201
        assert response.json()["patterns"]
        public_profile = client.get(f"/twins/{public_id}")
        assert public_profile.status_code == 200
        assert public_profile.json()["limitations"][0].startswith("Only creator-approved")
        assert "analysis" not in public_profile.json()
    finally:
        repository.delete_public_twin(public_id)
