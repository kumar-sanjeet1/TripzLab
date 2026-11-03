from pathlib import Path

import bootstrap


def configured(monkeypatch):
    monkeypatch.setenv("TRIPZ_AUTO_INSTALL", "true")
    monkeypatch.setenv("TRIPZ_BOOTSTRAP_ADMIN_TOKEN", "FAKE_TEST_TOKEN")


def test_same_source_is_not_overwritten(monkeypatch):
    configured(monkeypatch)
    calls = []

    def api(base, token, method, path, payload=None):
        calls.append((method, path))
        if path == "/health":
            return {"status": True}
        if path.endswith("/list"):
            return [{"id": bootstrap.FUNCTION_ID}]
        if path.endswith("/" + bootstrap.FUNCTION_ID):
            return {"content": bootstrap.FUNCTION_SOURCE.read_text(), "is_active": True}
        raise AssertionError("No mutation expected")

    monkeypatch.setattr(bootstrap, "api_call", api)
    monkeypatch.setattr(bootstrap, "install", lambda *a, **k: (_ for _ in ()).throw(AssertionError("No import expected")))
    bootstrap.main()
    assert all(method == "GET" for method, _ in calls)


def test_changed_source_backs_up_to_persistent_volume(monkeypatch, tmp_path):
    configured(monkeypatch)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    installed = []

    def api(base, token, method, path, payload=None):
        if path == "/health":
            return {"status": True}
        if path.endswith("/list"):
            return [{"id": bootstrap.FUNCTION_ID}]
        return {"content": "previous source", "is_active": True}

    monkeypatch.setattr(bootstrap, "api_call", api)
    monkeypatch.setattr(bootstrap, "install", lambda *a, **k: installed.append(k))
    bootstrap.main()
    backups = list((tmp_path / "tripz_backups").glob("*.py"))
    assert len(backups) == 1 and backups[0].read_text() == "previous source"
    assert installed == [{"update": True, "backup": False}]


def test_disabled_bootstrap_never_uses_credentials_or_api(monkeypatch):
    monkeypatch.setenv("TRIPZ_AUTO_INSTALL", "false")
    monkeypatch.setattr(bootstrap, "api_call", lambda *a, **k: (_ for _ in ()).throw(AssertionError("No network expected")))
    bootstrap.main()
