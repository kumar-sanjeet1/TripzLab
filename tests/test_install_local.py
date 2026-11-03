from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import install_local


def test_create_then_enable(monkeypatch, capsys):
    calls = []

    def fake_api(base, token, method, path, payload=None):
        calls.append((method, path, payload))
        if path == "/api/v1/functions/list":
            return []
        if path == "/api/v1/functions/create":
            assert payload["id"] == "tripz_image_studio"
            assert "class Pipe:" in payload["content"]
            return {"is_active": False}
        if path.endswith("/toggle"):
            return {"is_active": True}
        raise AssertionError(f"unexpected call: {method} {path}")

    monkeypatch.setattr(install_local, "api_call", fake_api)
    install_local.install("http://localhost:8080", "test-admin-key")
    assert [c[:2] for c in calls] == [
        ("GET", "/api/v1/functions/list"),
        ("POST", "/api/v1/functions/create"),
        ("POST", "/api/v1/functions/id/tripz_image_studio/toggle"),
    ]
    assert "test-admin-key" not in capsys.readouterr().out


def test_existing_pipe_not_replaced_without_opt_in(monkeypatch):
    def fake_api(base, token, method, path, payload=None):
        if path.endswith("list"):
            return [{"id": "tripz_image_studio", "is_active": True}]
        raise AssertionError("Shouldn't call write APIs")

    monkeypatch.setattr(install_local, "api_call", fake_api)
    try:
        install_local.install("http://localhost:8080", "test-admin-key")
    except install_local.InstallationError as exc:
        assert "--update" in str(exc)
    else:
        assert False, "Expected explicit --update guard"
