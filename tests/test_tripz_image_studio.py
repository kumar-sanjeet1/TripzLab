import base64
import io
import json
import sys
import types
from pathlib import Path

import httpx
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tripz_image_studio as studio


def make_img(format_="PNG"):
    im = Image.new("RGB", (16, 16), (72, 163, 241))
    out = io.BytesIO()
    im.save(out, format=format_)
    return out.getvalue()


def fake_open_webui(monkeypatch, recorded, *, image_url=None):
    packages = {}
    for name in (
        "open_webui",
        "open_webui.models",
        "open_webui.routers",
        "open_webui.models.config",
        "open_webui.models.users",
        "open_webui.routers.images",
    ):
        mod = types.ModuleType(name)
        mod.__path__ = []
        monkeypatch.setitem(sys.modules, name, mod)
        packages[name] = mod

    class Config:
        @staticmethod
        async def get(name):
            recorded["read_config_key"] = name
            return recorded.get("existing_key", "")

    class User:
        id = "user-123"
        role = "user"
        email = "example@example.com"
        name = "Editor"

    class Users:
        @staticmethod
        async def get_user_by_id(user_id):
            recorded["user_id"] = user_id
            return User()

    async def upload_image(request, data, content_type, metadata, user):
        recorded["file"] = (request, data, content_type, metadata, user)
        return object(), {"url": "/api/v1/files/mock/content", "id": "mock"}

    async def get_image_data(url):
        recorded["fetched_url"] = url
        return make_img("PNG"), "image/png"

    packages["open_webui.models.config"].Config = Config
    packages["open_webui.models.users"].Users = Users
    packages["open_webui.routers.images"].upload_image = upload_image
    packages["open_webui.routers.images"].get_image_data = get_image_data
    return packages


def intercept_http(monkeypatch, recorded, response_body, code=200):
    original_client = httpx.AsyncClient

    async def respond(request):
        recorded["request"] = request
        return httpx.Response(code, json=response_body)

    def fake_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(respond)
        return original_client(*args, **kwargs)

    monkeypatch.setattr(studio.httpx, "AsyncClient", fake_client)


async def render(pipe, *, model="tripz_image_studio.sunburst", content="A red fox", emitter=None, valves=None):
    return await pipe.pipe(
        body={"model": model, "messages": [{"role": "user", "content": content}], "stream": True},
        __user__={"id": "user-123", "valves": valves or {}},
        __request__=object(),
        __chat_id__="chat-123",
        __message_id__="msg-123",
        __event_emitter__=emitter,
    )


def fresh_pipe():
    pipe = studio.Pipe()
    pipe.valves.SHARED_AZURE_KEY = "TEST_TOP_SECRET_123"
    pipe.valves.SUNBURST_ENDPOINT = "https://test-resource.services.ai.azure.com/openai/v1/images/generations"
    pipe.valves.FLUX_ENDPOINT = "https://test-resource.services.ai.azure.com/providers/blackforestlabs/v1/flux-2-pro?api-version=preview"
    return pipe


def test_two_selectable_models():
    assert studio.Pipe().pipes() == [
        {"id": "sunburst", "name": "Tripz Image - GPT Image 2.5 Sunburst"},
        {"id": "flux", "name": "Tripz Image - FLUX.2 Pro"},
    ]


@pytest.mark.asyncio
async def test_sunburst_correct_payload_upload_and_event(monkeypatch):
    recorded = {}
    fake_open_webui(monkeypatch, recorded)
    image = make_img("PNG")
    intercept_http(monkeypatch, recorded, {"data": [{"b64_json": base64.b64encode(image).decode()}]})
    statuses = []

    async def emitter(event):
        statuses.append(event)

    answer = await render(fresh_pipe(), emitter=emitter)
    posted = json.loads(recorded["request"].content)
    assert recorded["request"].url.path == "/openai/v1/images/generations"
    assert recorded["request"].headers["authorization"] == "Bearer TEST_TOP_SECRET_123"
    assert posted == {
        "model": "gpt-image-2.5-sunburst", "prompt": "A red fox",
        "size": "1536x1920", "n": 1, "quality": "xhigh", "output_format": "png"
    }
    assert recorded["file"][1:3] == (image, "image/png")
    assert recorded["file"][3]["chat_id"] == "chat-123"
    assert recorded["file"][3]["requested_size"] == "1536x1920"
    assert recorded["file"][3]["size"] == "16x16"
    assert "![Generated with GPT Image 2.5 Sunburst](/api/v1/files/mock/content)" in answer
    assert "?attachment=true" in answer
    assert "TEST_TOP_SECRET_123" not in answer
    assert statuses[-1]["data"]["done"] is True


@pytest.mark.asyncio
async def test_flux_correct_provider_endpoint_and_no_gpt_quality_param(monkeypatch):
    recorded = {}
    fake_open_webui(monkeypatch, recorded)
    image = make_img("JPEG")
    intercept_http(monkeypatch, recorded, {"data": [{"b64_json": base64.b64encode(image).decode()}]})

    answer = await render(fresh_pipe(), model="tripz_image_studio.flux", valves={"IMAGE_SIZE": "2048x1152"})
    posted = json.loads(recorded["request"].content)
    assert recorded["request"].url.path == "/providers/blackforestlabs/v1/flux-2-pro"
    assert recorded["request"].url.params["api-version"] == "preview"
    assert posted == {
        "model": "FLUX.2-pro", "prompt": "A red fox", "width": 2048, "height": 1152,
        "num_images": 1, "output_format": "jpeg"
    }
    assert recorded["file"][2] == "image/jpeg"
    assert "FLUX.2 Pro" in answer and "16x16" in answer
    assert recorded["file"][3]["requested_size"] == "2048x1152"


@pytest.mark.asyncio
async def test_azure_img_key_read_from_existing_open_webui_images_settings(monkeypatch):
    recorded = {"existing_key": "existing-openwebui-image-key"}
    fake_open_webui(monkeypatch, recorded)
    intercept_http(monkeypatch, recorded, {"data": [{"b64_json": base64.b64encode(make_img()).decode()}]})
    pipe = fresh_pipe()
    pipe.valves.SHARED_AZURE_KEY = ""
    await render(pipe)
    assert recorded["read_config_key"] == "image_generation.openai.api_key"
    assert recorded["request"].headers["authorization"] == "Bearer existing-openwebui-image-key"


@pytest.mark.asyncio
async def test_flux_returns_image_url_and_is_safely_fetched(monkeypatch):
    recorded = {}
    fake_open_webui(monkeypatch, recorded)
    intercept_http(monkeypatch, recorded, {"images": [{"url": "https://example.blob.core.windows.net/image.png"}]})
    await render(fresh_pipe(), model="tripz_image_studio.flux")
    assert recorded["fetched_url"] == "https://example.blob.core.windows.net/image.png"
    assert recorded["file"][2] == "image/png"


@pytest.mark.asyncio
async def test_rate_limit_message_does_not_leak_credentials(monkeypatch):
    recorded = {}
    fake_open_webui(monkeypatch, recorded)
    intercept_http(monkeypatch, recorded, {"error": {"message": "YOUR SECRET TEST_TOP_SECRET_123"}}, code=429)
    with pytest.raises(studio.ImageStudioError, match="rate limit") as exc:
        await render(fresh_pipe())
    assert "TEST_TOP_SECRET_123" not in str(exc.value)


@pytest.mark.asyncio
async def test_bad_endpoint_does_not_issue_request(monkeypatch):
    pipe = fresh_pipe()
    pipe.valves.FLUX_ENDPOINT = "http://169.254.169.254/providers/blackforestlabs/v1/flux-2-pro"
    with pytest.raises(studio.ImageStudioError, match="invalid"):
        await pipe._generate(model="flux", prompt="hello", size="1024x1024", quality="high")


@pytest.mark.asyncio
async def test_bad_credentials_error_is_not_returned_from_response_body(monkeypatch):
    recorded = {}
    fake_open_webui(monkeypatch, recorded)
    intercept_http(monkeypatch, recorded, {"error": {"message": "TEST_TOP_SECRET_123 credential"}}, code=401)
    with pytest.raises(studio.ImageStudioError, match="authentication") as exc:
        await render(fresh_pipe(), model="tripz_image_studio.flux")
    assert "TEST_TOP_SECRET_123" not in str(exc.value)


def test_last_user_prompt_ignores_old_chat_messages():
    messages = [
        {"role": "user", "content": "old prompt"},
        {"role": "assistant", "content": "old image"},
        {"role": "user", "content": [{"type": "text", "text": " latest scene "}]},
    ]
    assert studio._last_user_prompt(messages) == "latest scene"


def test_reference_edits_not_silently_ignored():
    with pytest.raises(studio.ImageStudioError, match="editing"):
        studio._last_user_prompt([{"role": "user", "content": [
            {"type": "text", "text": "Make this brighter"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
        ]}])


def test_unexpected_response_format():
    with pytest.raises(studio.ImageStudioError, match="no supported image field"):
        studio._find_image_result({"data": [{"surprise": "format"}]})


def test_all_sizes_under_4_megapixels_and_divisible_by_16():
    for size in studio.IMAGE_SIZES:
        w, h = map(int, size.split("x"))
        assert w % 16 == 0 and h % 16 == 0
        assert w * h <= 4_000_000
