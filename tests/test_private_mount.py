"""The private-Twins backend (private_twins/backend) is mounted under /private on this app."""
import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)
CSV = "date,symbol,side,qty,price\n2025-01-02,AAPL,BUY,5,100\n2025-01-03,AAPL,SELL,5,110\n"


def test_a_health_shape_unchanged():
    assert client.get("/health").json() == {"ok": True}


def test_a_gurus_shape_unchanged():
    response = client.get("/gurus")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
    for guru in response.json():
        assert set(guru) == {"id", "name", "style", "bio", "n_insights", "holdout_match"}


def test_b_health_under_prefix():
    response = client.get("/private/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "twin-engine"}


def test_b_openapi_lists_b_routes():
    paths = client.get("/private/openapi.json").json()["paths"]
    for path in ["/health", "/runs", "/runs/{run_id}", "/twins", "/twins/{twin_id}",
                 "/twins/{twin_id}/chat", "/twins/{twin_id}/speak", "/me/portfolios/latest",
                 "/me/creator-twin", "/me/conversations", "/me/conversations/{conversation_id}",
                 "/me/conversations/{conversation_id}/messages"]:
        assert path in paths


def test_a_and_b_runs_do_not_collide():
    assert "/runs" in client.get("/openapi.json").json()["paths"]
    assert client.get("/runs/not-a-run").json() == {"error": "Run not found"}
    assert client.get("/private/runs/not-a-run").status_code == 404


def test_b_twin_list_works():
    ids = [t["id"] for t in client.get("/private/twins").json()["twins"]]
    assert "alex-demo" in ids


def test_b_chat_without_key_is_a_clear_503(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    response = client.post("/private/twins/alex-demo/chat", json={"message": "How long do you hold?"})
    assert response.status_code == 503
    assert "OPENAI_API_KEY" in response.json()["detail"]


def test_b_speech_without_key_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("FISH_AUDIO_API_KEY", raising=False)
    # A privacy-reply answer needs no OpenAI key, so we can obtain a real answer_id offline.
    chat = client.post("/private/twins/alex-demo/chat", json={"message": "Can you see my uploaded CSV?"}).json()
    response = client.post("/private/twins/alex-demo/speak", json={"answer_id": chat["answer_id"]})
    assert response.status_code == 503
    assert "FISH_AUDIO_API_KEY" in response.json()["detail"]


def test_exactly_one_cors_layer():
    response = client.get("/private/health", headers={"Origin": "https://x.base44.app"})
    # A second layer would repeat the header
    assert len(response.headers.get_list("access-control-allow-origin")) == 1
    preflight = client.options("/private/runs", headers={
        "Origin": "https://x.base44.app", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "x-demo-user"})
    assert preflight.status_code == 200
    assert len(preflight.headers.get_list("access-control-allow-origin")) == 1


def test_private_routes_require_auth_by_default(monkeypatch):
    monkeypatch.delenv("DEMO_AUTH", raising=False)
    # AUTH_MODE=development (the demo default): no identity header -> 401; X-Demo-User is ignored without DEMO_AUTH
    assert client.get("/private/me/portfolios/latest").status_code == 401
    assert client.get("/private/me/portfolios/latest", headers={"X-Demo-User": "u1"}).status_code == 401
    # X-Dev-User-Id IS accepted in development mode (B's own mechanism): the user has no portfolio yet -> 404
    assert client.get("/private/me/portfolios/latest", headers={"X-Dev-User-Id": "u1"}).status_code == 404


def test_clerk_mode_rejects_dev_header(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "clerk")
    assert client.get("/private/me/portfolios/latest", headers={"X-Dev-User-Id": "u1"}).status_code == 401


def test_demo_auth_accepts_header(monkeypatch):
    monkeypatch.setenv("DEMO_AUTH", "1")
    headers = {"X-Demo-User": "demo-user-1"}
    assert client.get("/private/me/conversations", headers=headers).json() == {"conversations": []}
    assert client.get("/private/me/conversations").status_code == 401  # header still required
    assert client.get("/private/me/conversations", headers={"X-Demo-User": "bad user!"}).status_code == 400


def test_demo_auth_private_upload_and_conversation_isolation(monkeypatch):
    monkeypatch.setenv("DEMO_AUTH", "1")
    owner = {"X-Demo-User": "owner-1"}
    upload = client.post("/private/runs", files={"file": ("t.csv", CSV, "text/csv")}, headers=owner)
    assert upload.status_code == 202
    # background task has finished by the time TestClient returns
    assert client.get("/private/me/portfolios/latest", headers=owner).json()["run_id"] == upload.json()["run_id"]
    assert client.get("/private/me/portfolios/latest", headers={"X-Demo-User": "other"}).status_code == 404
    conv = client.post("/private/me/conversations", json={"twin_id": "alex-demo"}, headers=owner).json()
    assert client.get(f"/private/me/conversations/{conv['id']}", headers={"X-Demo-User": "other"}).status_code == 404
    assert client.get(f"/private/me/conversations/{conv['id']}", headers=owner).status_code == 200


def _stub_anthropic(monkeypatch, text="From my published history, I held for about three days."):
    import types
    calls = {}

    class FakeMessages:
        def create(self, **kwargs):
            calls.update(kwargs)
            return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=text)])

    monkeypatch.setattr("anthropic.Anthropic", lambda **kw: types.SimpleNamespace(messages=FakeMessages()))
    return calls


def test_chat_falls_back_to_anthropic(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-real-key")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    calls = _stub_anthropic(monkeypatch)
    response = client.post("/private/twins/alex-demo/chat", json={"message": "How long do you hold?"})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"twin_id", "answer", "answer_id", "evidence", "limitations", "disclaimer"}
    assert body["answer"].startswith("From my published history")
    assert calls["model"] == "claude-sonnet-5-5"
    assert "Never give investment advice" in calls["system"]
    assert calls["messages"] == [{"role": "user", "content": "How long do you hold?"}]


def test_openai_key_wins_over_anthropic(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-a-real-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-real-key")
    monkeypatch.setattr("app.services.twin_chat.httpx.Client", _fake_openai_client)
    _stub_anthropic(monkeypatch, text="should not be used")
    response = client.post("/private/twins/alex-demo/chat", json={"message": "How long do you hold?"})
    assert response.json()["answer"] == "openai answer"


def _fake_openai_client(*args, **kwargs):
    import types

    class Client:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, *a, **kw):
            return types.SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {"choices": [{"message": {"content": "openai answer"}}]})
    return Client()


def test_anthropic_failure_is_502_json(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-real-key")

    def boom(**kw):
        raise ConnectionError("down")
    monkeypatch.setattr("anthropic.Anthropic", boom)
    response = client.post("/private/twins/alex-demo/chat", json={"message": "hi"})
    assert response.status_code == 502
    assert "Anthropic provider request failed" in response.json()["detail"]


def test_no_chat_key_is_503_json_not_500(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    response = client.post("/private/twins/alex-demo/chat", json={"message": "hi"})
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_cors_origins_env(monkeypatch):
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    assert main.cors_origins() == ["*"]
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://a.app, https://b.app")
    assert main.cors_origins() == ["https://a.app", "https://b.app"]
    monkeypatch.setenv("ALLOWED_ORIGINS", "*")
    assert main.cors_origins() == ["*"]


def test_demo_twins_present_without_database_rows():
    ids = [t["id"] for t in client.get("/private/twins").json()["twins"]]
    assert {"alex-demo", "maya-demo", "jack-demo", "lena-demo", "daniel-demo", "sofia-demo"} <= set(ids)
