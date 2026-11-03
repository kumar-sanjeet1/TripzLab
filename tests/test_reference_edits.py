import base64
from email import policy
from email.parser import BytesParser

import pytest

import tripz_image_studio as studio
from test_tripz_image_studio import fake_open_webui, fresh_pipe, intercept_http, make_img, render


def result_image():
    return {"data": [{"b64_json": base64.b64encode(make_img()).decode()}]}


def multipart(request):
    message = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n" + request.content
    )
    return [(part.get_param("name", header="content-disposition"), part.get_payload(decode=True))
            for part in message.iter_parts()]


@pytest.mark.asyncio
async def test_inline_reference_uses_multipart_edit_route(monkeypatch):
    recorded = {}
    fake_open_webui(monkeypatch, recorded)
    intercept_http(monkeypatch, recorded, result_image())
    inline = "data:image/png;base64," + base64.b64encode(make_img()).decode()
    answer = await render(fresh_pipe(), content=[
        {"type": "text", "text": "Replace the square with a circle"},
        {"type": "image_url", "image_url": {"url": inline}},
    ])
    req = recorded["request"]
    assert req.url.path == "/openai/v1/images/edits"
    parts = multipart(req)
    assert ("image[]", make_img()) in parts
    assert ("prompt", b"Replace the square with a circle") in parts
    assert ("quality", b"xhigh") in parts
    assert ("size", b"1536x1920") in parts
    assert recorded["file"][3]["operation"] == "edit"
    assert recorded["file"][3]["reference_count"] == 1
    assert "Download original image" in answer


@pytest.mark.asyncio
async def test_uploaded_file_and_url_are_deduplicated_and_resolved_as_user(monkeypatch):
    recorded = {}
    fake_open_webui(monkeypatch, recorded)
    intercept_http(monkeypatch, recorded, result_image())
    await fresh_pipe().pipe(
        {"model": "tripz_image_studio.sunburst", "messages": [{"role": "user", "content": [
            {"type": "text", "text": "Make it brighter"},
            {"type": "image_url", "image_url": {"url": "/api/v1/files/own-file/content"}},
        ]}]}, __user__={"id": "user-123"}, __request__=object(),
        __files__=[{"type": "file", "file": {"id": "own-file"}}],
    )
    assert recorded["reference_reads"] == [("own-file", "user-123")]
    assert len([p for p in multipart(recorded["request"]) if p[0] == "image[]"]) == 1


@pytest.mark.asyncio
async def test_unreadable_reference_never_reaches_azure(monkeypatch):
    recorded = {}
    fake_open_webui(monkeypatch, recorded)
    intercept_http(monkeypatch, recorded, result_image())
    with pytest.raises(studio.ImageStudioError, match="permission"):
        await render(fresh_pipe(), content=[
            {"type": "text", "text": "Edit"},
            {"type": "image_url", "image_url": {"url": "/api/v1/files/unreadable-file/content"}},
        ])
    assert "request" not in recorded


def test_previous_result_is_reused_only_when_enabled_and_no_upload():
    messages = [{"role": "assistant", "content": "![Generated with GPT Image 2.5 Sunburst](/api/v1/files/previous/content)"},
                {"role": "user", "content": "Make it blue"}]
    assert studio._reference_sources(messages, None, True) == ["previous"]
    assert studio._reference_sources(messages, None, False) == []
    assert studio._reference_sources(messages, [{"id": "new-upload"}], True) == ["new-upload"]


@pytest.mark.asyncio
async def test_flux_upload_is_not_silently_sent_as_text(monkeypatch):
    recorded = {}
    fake_open_webui(monkeypatch, recorded)
    intercept_http(monkeypatch, recorded, result_image())
    with pytest.raises(studio.ImageStudioError, match="Sunburst"):
        await render(fresh_pipe(), model="tripz_image_studio.flux", content=[
            {"type": "text", "text": "Edit"}, {"type": "image_url", "image_url": {"url": "own-file"}},
        ])
    assert "request" not in recorded


def test_external_links_and_too_many_references_are_rejected():
    with pytest.raises(studio.ImageStudioError, match="attachment"):
        studio._reference_sources([], [{"url": "http://169.254.169.254/image.png"}], False)
    with pytest.raises(studio.ImageStudioError, match="16 reference"):
        studio._reference_sources([], [{"id": f"file-{i}"} for i in range(17)], False)
