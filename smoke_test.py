#!/usr/bin/env python3
"""Check model visibility; --generate tests both Azure models and original downloads.

Run on the computer hosting Open WebUI. No third-party Python packages needed.
The default check does not request an image; --generate makes two paid API calls.
"""
import argparse
import getpass
import json
import os
import re
from pathlib import Path
from urllib import parse, request, error

from install_local import FUNCTION_ID, InstallationError, api_call


PROMPT = (
    "A premium editorial travel photograph for TripzSearch. Four young adult "
    "Indian friends beside a turquoise alpine lake in Himachal Pradesh at sunrise. "
    "Realistic faces and anatomy, natural candid expressions, tasteful hiking outfits, "
    "atmospheric mountains, fine textures, gentle cinematic light. Clean composition "
    "and generous upper-third negative space for a headline. No text, no logos, no watermarks."
)


def authenticate(base):
    token = os.getenv("OPENWEBUI_ADMIN_API_KEY", "").strip()
    if token:
        return token
    email = input("Open WebUI account email: ").strip()
    password = getpass.getpass("Open WebUI password (hidden, never saved): ")
    auth = api_call(base, "", "POST", "/api/v1/auths/signin", {"email": email, "password": password})
    token = (auth or {}).get("token", "")
    if not token:
        raise InstallationError("Sign-in needs MFA or another step. Use an existing Open WebUI API key in OPENWEBUI_ADMIN_API_KEY.")
    return token


def check(base, token, generate=False, output=Path("test-output")):
    response = api_call(base, token, "GET", "/api/models")
    models = response.get("data", []) if isinstance(response, dict) else response
    ids = {m["id"] for m in models}
    expected = [FUNCTION_ID + ".sunburst", FUNCTION_ID + ".flux"]
    for model_id in expected:
        if model_id not in ids:
            raise InstallationError(f"Model is not visible to this account: {model_id}")
        print("Visible:", model_id)
    if not generate:
        print("Visibility passed. No image requests made. Add --generate to test both models and downloads.")
        return
    output.mkdir(parents=True, exist_ok=True)
    report = {"status": "running", "models": []}
    for model_id in expected:
        print("Generating one travel image with", model_id, "...", flush=True)
        req = request.Request(
            base + "/api/chat/completions",
            data=json.dumps({"model": model_id, "stream": False, "messages": [{"role": "user", "content": PROMPT}]}).encode(),
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        )
        try:
            with request.urlopen(req, timeout=300) as resp:
                result = json.load(resp)
        except (error.URLError, TimeoutError):
            raise InstallationError(f"Generation failed for {model_id}; inspect the Open WebUI chat or backend logs.") from None
        try:
            text = result["choices"][0]["message"]["content"]
            match = re.search(r"!\[[^\]]*\]\((/api/v1/files/[^)]+/content)\)", text)
            if not match:
                raise ValueError()
            image_path = match.group(1)
        except (KeyError, IndexError, TypeError, ValueError):
            raise InstallationError(f"No image/download returned for {model_id}.") from None
        req = request.Request(base + image_path + "?attachment=true", headers={"Authorization": "Bearer " + token})
        with request.urlopen(req, timeout=60) as resp:
            content_type = resp.headers.get("Content-Type", "").split(";")[0]
            data = resp.read(32 * 1024 * 1024 + 1)
            disposition = resp.headers.get("Content-Disposition", "")
        if len(data) > 32 * 1024 * 1024 or not data or not content_type.startswith("image/"):
            raise InstallationError(f"Original image download is invalid for {model_id}.")
        suffix = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}.get(content_type)
        if not suffix or not disposition.startswith("attachment"):
            raise InstallationError(f"Original download headers are invalid for {model_id}.")
        path = output / (model_id.rsplit(".", 1)[-1] + suffix)
        path.write_bytes(data)
        report["models"].append({"id": model_id, "image": path.name, "bytes": len(data), "mime": content_type})
        print("Downloaded:", path)
    report["status"] = "passed"
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("Both generation requests and original downloads passed. Inspect the images in Open WebUI too.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8080")
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("test-output"))
    args = parser.parse_args()
    base = args.url.rstrip("/")
    parsed = parse.urlparse(base)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or parsed.username or parsed.password or parsed.path:
        parser.error("Run locally against the Open WebUI root URL.")
    try:
        check(base, authenticate(base), args.generate, args.output)
    except InstallationError as exc:
        parser.exit(1, f"Check: {exc}\n")


if __name__ == "__main__":
    main()
