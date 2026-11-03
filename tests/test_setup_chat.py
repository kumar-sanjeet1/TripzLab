import copy

import pytest

import setup_chat as chat
from install_local import InstallationError


def test_chat_model_selection_excludes_image_and_audio_models():
    assert chat.choose_model([{"id": name} for name in ["gpt-image-2.5-sunburst", "gpt-audio", "gpt-4.1", "gpt-6-sol"]]) == "gpt-6-sol"
    assert chat.choose_model([], "my-deployed-sol") == "my-deployed-sol"
    with pytest.raises(InstallationError, match="deployed chat model"):
        chat.choose_model([{"id": "gpt-image-2.5-sunburst"}])


def test_native_connection_preserves_other_connections_and_secrets():
    previous = {"ENABLE_OPENAI_API": False, "OPENAI_API_BASE_URLS": ["https://other.example/v1", "https://api.openai.com/v1"],
                "OPENAI_API_KEYS": ["existing-secret", ""], "OPENAI_API_CONFIGS": {"0": {"model_ids": ["other-model"]}}}
    snapshot = copy.deepcopy(previous)
    updated = chat.connection_config(previous, "https://test.services.ai.azure.com/openai/v1", "new-secret", "sol-deployment")
    assert previous == snapshot
    assert updated["OPENAI_API_KEYS"][0] == "existing-secret"
    assert updated["OPENAI_API_CONFIGS"]["0"] == previous["OPENAI_API_CONFIGS"]["0"]
    assert updated["OPENAI_API_CONFIGS"]["1"]["enable"] is False
    assert updated["OPENAI_API_CONFIGS"]["2"]["model_ids"] == ["sol-deployment"]
    repeated = chat.connection_config(updated, "https://test.services.ai.azure.com/openai/v1", "new-secret", "sol-deployment")
    assert repeated == updated


def test_failed_chat_verification_restores_previous_configuration(monkeypatch, capsys):
    monkeypatch.setenv("TRIPZ_CHAT_BASE_URL", "https://test.services.ai.azure.com/openai/v1")
    monkeypatch.setenv("TRIPZ_CHAT_DEPLOYMENT", "sol-deployment")
    monkeypatch.setenv("TRIPZ_AZURE_FOUNDRY_API_KEY", "SECRET_SHOULD_NOT_PRINT")
    previous = {"ENABLE_OPENAI_API": False, "OPENAI_API_BASE_URLS": [], "OPENAI_API_KEYS": [], "OPENAI_API_CONFIGS": {}}
    writes = []

    def api(base, token, method, path, payload=None, **kwargs):
        if path == "/openai/config":
            return previous
        if path == "/openai/config/update":
            writes.append(payload)
            return payload
        raise InstallationError("Provider not deployed")

    monkeypatch.setattr(chat, "api_call", api)
    with pytest.raises(InstallationError, match="actual Azure chat deployment"):
        chat.setup_chat("http://localhost:8080", "internal-token")
    assert writes[-1] == previous
    assert "SECRET_SHOULD_NOT_PRINT" not in capsys.readouterr().out


def test_chat_base_url_is_derived_and_validated(monkeypatch):
    monkeypatch.delenv("TRIPZ_CHAT_BASE_URL", raising=False)
    monkeypatch.setenv("TRIPZ_SUNBURST_ENDPOINT", "https://test.services.ai.azure.com/openai/v1/images/generations")
    assert chat.chat_base_url() == "https://test.services.ai.azure.com/openai/v1"
    monkeypatch.setenv("TRIPZ_CHAT_BASE_URL", "http://127.0.0.1/openai/v1")
    with pytest.raises(InstallationError, match="Azure HTTPS"):
        chat.chat_base_url()
