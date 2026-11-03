"""Run one explicit reference-edit check in the real Open WebUI request pipeline.

The marker is written before any generation request, so restarts never repeat a
paid request for the same test ID. Uses only a synthetic reference image.
"""
import io
import json
import os
from pathlib import Path
import re

import httpx
from PIL import Image, ImageDraw


def verify_edits(base, token):
    check_id = os.getenv("TRIPZ_EDIT_SMOKE_TEST_ID", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", check_id):
        raise ValueError("Invalid reference-edit verification ID")
    folder = Path(os.getenv("DATA_DIR", "/app/backend/data")) / "tripz_checks"
    folder.mkdir(parents=True, exist_ok=True)
    report_path = folder / ("edit-" + check_id + ".json")
    if report_path.exists():
        report = json.loads(report_path.read_text())
        print(f"Tripz reference-edit verification already attempted: {report.get('status', 'unknown')}. No new image request was made.")
        return
    report = {"id": check_id, "status": "started"}
    report_path.write_text(json.dumps(report) + "\n")
    try:
        reference = Image.new("RGB", (128, 128), "#0B6BCB")
        ImageDraw.Draw(reference).rectangle((40, 40, 88, 88), fill="white")
        content = io.BytesIO()
        reference.save(content, format="PNG")
        headers = {"Authorization": "Bearer " + token}
        with httpx.Client(timeout=300, follow_redirects=False) as client:
            uploaded = client.post(base + "/api/v1/files/", params={"process": "false"}, headers=headers,
                                   files={"file": ("tripz-reference-check.png", content.getvalue(), "image/png")})
            uploaded.raise_for_status()
            ref_id = uploaded.json()["id"]
            response = client.post(base + "/api/chat/completions", headers=headers, json={
                "model": "tripz_image_studio.sunburst", "stream": False,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": "Edit this reference image: keep the blue background, replace the white square with a white circle in the same position. No text."},
                    {"type": "image_url", "image_url": {"url": f"/api/v1/files/{ref_id}/content"}},
                ]}],
            })
            response.raise_for_status()
            answer = response.json()["choices"][0]["message"]["content"]
            match = re.search(r"!\[[^\]]*\]\((/api/v1/files/[^)]+/content)\)", answer)
            if not match:
                raise ValueError("No reference edit was returned")
            image_path = match.group(1)
            image = client.get(base + image_path, headers=headers)
            image.raise_for_status()
            with Image.open(io.BytesIO(image.content)) as result:
                result.verify()
            with Image.open(io.BytesIO(image.content)) as result:
                report.update({"status": "passed", "reference_file_id": ref_id, "result_url": image_path,
                               "width": result.width, "height": result.height, "bytes": len(image.content)})
        print(f"Tripz reference-edit verification PASSED: real upload, Azure edit, and original download; {report['width']}x{report['height']}.")
    except Exception as exc:
        report.update({"status": "failed", "error_type": type(exc).__name__})
        print(f"Tripz reference-edit verification FAILED ({type(exc).__name__}). The test will not retry automatically.")
        raise
    finally:
        report_path.write_text(json.dumps(report, indent=2) + "\n")
