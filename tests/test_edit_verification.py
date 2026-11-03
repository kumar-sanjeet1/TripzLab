import json

import verify_edits


def test_restart_does_not_repeat_a_paid_edit_request(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRIPZ_EDIT_SMOKE_TEST_ID", "once")
    folder = tmp_path / "tripz_checks"
    folder.mkdir()
    (folder / "edit-once.json").write_text(json.dumps({"status": "started"}))
    monkeypatch.setattr(verify_edits.httpx, "Client", lambda **k: (_ for _ in ()).throw(AssertionError("No retry allowed")))
    verify_edits.verify_edits("http://localhost:8080", "test-token")
    assert "No new image request" in capsys.readouterr().out
