from app.services.fish_audio import reference_id_for_twin


def test_specific_twin_voice_overrides_the_demo_fallback(monkeypatch) -> None:
    monkeypatch.setenv("FISH_AUDIO_REFERENCE_ID", "fallback")
    monkeypatch.setenv("FISH_AUDIO_REFERENCE_ID_MAYA_DEMO", "maya-voice")
    assert reference_id_for_twin("maya-demo") == "maya-voice"
    assert reference_id_for_twin("alex-demo") == "fallback"
