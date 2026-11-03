#!/usr/bin/env python3
"""Install/update the Tripz Image Studio Pipe in a local Open WebUI admin account.

Usage:
  python3 install_local.py
  python3 install_local.py --update

No Azure credentials are needed in this installer. The Open WebUI admin API
key is requested interactively and used only to authenticate requests to your
Open WebUI server. It is never written to disk.
"""

import argparse
import getpass
import json
import os
from pathlib import Path
from urllib import error, parse, request
from datetime import datetime, timezone

FUNCTION_ID = "tripz_image_studio"
FUNCTION_NAME = "TripzSearch Azure Image Studio"
FUNCTION_SOURCE = Path(__file__).with_name("tripz_image_studio.py")


class InstallationError(Exception):
    pass


def api_call(base: str, token: str, method: str, path: str, payload=None):
    encoded = None if payload is None else json.dumps(payload).encode("utf-8")
    req = request.Request(
        f"{base.rstrip('/')}{path}",
        method=method,
        data=encoded,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=25) as resp:
            content = resp.read()
            return json.loads(content) if content else None
    except error.HTTPError as exc:
        if path == "/api/v1/auths/signin" and exc.code == 400:
            raise InstallationError(
                "Administrator sign-in was rejected (HTTP 400). WEBUI_ADMIN_PASSWORD "
                "creates the initial account; changing it does not reset an existing "
                "account password. Use the saved account password or a valid admin token."
            ) from None
        if exc.code in (401, 403):
            raise InstallationError(
                f"Open WebUI rejected the admin API key (HTTP {exc.code}). "
                "Enable API Keys and use a key from an admin account."
            ) from None
        if exc.code == 404:
            raise InstallationError(
                "The Functions API was not found (HTTP 404). Check your Open WebUI URL/version."
            ) from None
        raise InstallationError(
            f"Open WebUI API returned HTTP {exc.code}. Review the admin console logs."
        ) from None
    except error.URLError:
        raise InstallationError(
            "Couldn't reach Open WebUI. Confirm it's running at the URL you provided."
        ) from None


def install(base: str, token: str, *, update: bool = False, backup: bool = True):
    # Inspect the authenticated admin endpoint rather than relying on a 401/404
    # from the individual Function read endpoint, which uses 401 for not found.
    functions = api_call(base, token, "GET", "/api/v1/functions/list")
    if not isinstance(functions, list):
        raise InstallationError("The Functions API did not return a valid list.")
    existing = next((f for f in functions if f.get("id") == FUNCTION_ID), None)

    if existing and not update:
        raise InstallationError(
            f"Function '{FUNCTION_ID}' already exists. Pass --update to back it up and replace the code."
        )
    source = FUNCTION_SOURCE.read_text(encoding="utf-8")
    form = {
        "id": FUNCTION_ID,
        "name": FUNCTION_NAME,
        "content": source,
        "meta": {"description": "Two Azure Foundry image models in Open WebUI: Sunburst + FLUX.2 Pro."},
    }

    if existing:
        old = api_call(base, token, "GET", f"/api/v1/functions/id/{FUNCTION_ID}")
        old_source = old.get("content", "")
        backup_path = FUNCTION_SOURCE.with_name(
            f"tripz_image_studio_backup_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.py"
        )
        if backup:
            backup_path.write_text(old_source, encoding="utf-8")
            print(f"Saved previous code locally: {backup_path.name}")
        updated = api_call(base, token, "POST", f"/api/v1/functions/id/{FUNCTION_ID}/update", form)
        status = bool(updated.get("is_active", existing.get("is_active", False)))
        print(f"Updated: {FUNCTION_NAME}")
    else:
        created = api_call(base, token, "POST", "/api/v1/functions/create", form)
        status = bool(created.get("is_active", False))
        print(f"Created: {FUNCTION_NAME}")

    if not status:
        toggled = api_call(base, token, "POST", f"/api/v1/functions/id/{FUNCTION_ID}/toggle")
        if not toggled or not toggled.get("is_active"):
            raise InstallationError("Function saved, but it could not be enabled.")
        print("Enabled the Pipe Function.")
    else:
        print("Pipe Function is already enabled.")
    print("Done. Open New Chat and select 'Tripz Image - GPT Image 2.5 Sunburst' or 'Tripz Image - FLUX.2 Pro'.")
    print("Check Admin Panel -> Functions -> TripzSearch Azure Image Studio -> Valves for endpoints and API key.")


def main():
    parser = argparse.ArgumentParser(description="Install TripzSearch Image Studio into Open WebUI.")
    parser.add_argument("--url", default="http://localhost:8080", help="Local Open WebUI base URL")
    parser.add_argument("--update", action="store_true", help="Back up and update an existing Function")
    args = parser.parse_args()

    url = args.url.rstrip("/")
    parsed = parse.urlparse(url)
    # Prevent accidentally posting a privileged admin bearer token to a public URL.
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        parser.error("Installer is intentionally limited to local http://localhost or http://127.0.0.1. Do not use on Railway yet.")
    try:
        api_key = os.getenv("OPENWEBUI_ADMIN_API_KEY", "").strip()
        if not api_key:
            email = input("Local Open WebUI administrator email: ").strip()
            password = getpass.getpass("Local Open WebUI password (hidden, never saved): ")
            auth = api_call(url, "", "POST", "/api/v1/auths/signin", {"email": email, "password": password})
            api_key = (auth or {}).get("token", "")
            if not api_key or (auth or {}).get("role") != "admin":
                raise InstallationError("Sign in as an administrator. If MFA is required, use an existing admin API key via OPENWEBUI_ADMIN_API_KEY.")
        install(url, api_key, update=args.update)
    except InstallationError as exc:
        parser.exit(1, f"Installer: {exc}\n")


if __name__ == "__main__":
    main()
