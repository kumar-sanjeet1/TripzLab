"""Idempotently install this image's Pipe after the Open WebUI server is ready.

Credentials stay in the process. Source is installed through the authenticated
Functions API; this script does not edit Open WebUI's database.
"""
import os
import time
from pathlib import Path

from install_local import FUNCTION_ID, FUNCTION_SOURCE, InstallationError, api_call, install


def main():
    image_setup = os.getenv("TRIPZ_AUTO_INSTALL", "true").lower() == "true"
    chat_setup = os.getenv("TRIPZ_CHAT_AUTO_SETUP", "false").lower() == "true"
    edit_check = bool(os.getenv("TRIPZ_EDIT_SMOKE_TEST_ID", "").strip())
    if not (image_setup or chat_setup or edit_check):
        print("Tripz automatic import disabled; existing database Function is retained.")
        return
    email = os.getenv("WEBUI_ADMIN_EMAIL", "").strip()
    password = os.getenv("WEBUI_ADMIN_PASSWORD", "")
    token = os.getenv("TRIPZ_BOOTSTRAP_ADMIN_TOKEN", "").strip()
    if not token and not (email and password):
        raise InstallationError(
            "First launch needs WEBUI_ADMIN_EMAIL and WEBUI_ADMIN_PASSWORD, or "
            "TRIPZ_BOOTSTRAP_ADMIN_TOKEN. After importing, set TRIPZ_AUTO_INSTALL=false "
            "before removing bootstrap credentials."
        )
    base = "http://127.0.0.1:" + os.getenv("PORT", "8080")
    deadline = time.monotonic() + 240
    while True:
        try:
            api_call(base, "", "GET", "/health")
            break
        except InstallationError:
            if time.monotonic() >= deadline:
                raise InstallationError("Open WebUI did not become healthy in 240 seconds.") from None
            time.sleep(2)
    if not token:
        auth = api_call(base, "", "POST", "/api/v1/auths/signin", {"email": email, "password": password})
        token = (auth or {}).get("token", "")
        if not token:
            raise InstallationError("Admin sign-in did not return a token. Complete MFA in the UI and use a bootstrap token.")
    if image_setup:
        ensure_image_pipe(base, token)
    if chat_setup:
        try:
            from setup_chat import setup_chat
            setup_chat(base, token)
        except InstallationError as exc:
            print(f"Tripz chat setup: {exc}")
    if edit_check:
        try:
            from verify_edits import verify_edits
            verify_edits(base, token)
        except Exception:
            print("Tripz reference-edit verification did not pass. Inspect the saved verification report.")


def ensure_image_pipe(base, token):
    functions = api_call(base, token, "GET", "/api/v1/functions/list")
    existing = next((f for f in functions if f.get("id") == FUNCTION_ID), None)
    if existing:
        previous = api_call(base, token, "GET", f"/api/v1/functions/id/{FUNCTION_ID}")
        if previous.get("content") == FUNCTION_SOURCE.read_text(encoding="utf-8"):
            if not previous.get("is_active"):
                api_call(base, token, "POST", f"/api/v1/functions/id/{FUNCTION_ID}/toggle")
            print("Tripz image models are installed and enabled.")
            return
    # Source backups are local to the persistent data volume; no secret values are copied.
    if existing:
        from datetime import datetime, timezone
        backup_dir = Path(os.getenv("DATA_DIR", "/app/backend/data")) / "tripz_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".py")
        backup.write_text(previous.get("content", ""), encoding="utf-8")
    install(base, token, update=bool(existing), backup=not bool(existing))


if __name__ == "__main__":
    try:
        main()
    except InstallationError as exc:
        raise SystemExit(f"Tripz bootstrap: {exc}") from None
