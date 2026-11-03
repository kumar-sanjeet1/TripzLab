import base64
from types import SimpleNamespace

import pytest

import tripz_image_studio as studio
from test_tripz_image_studio import fake_open_webui, fresh_pipe, intercept_http, make_img, render


@pytest.mark.asyncio
async def test_background_tasks_never_generate(monkeypatch):
    async def forbidden(**kwargs):
        raise AssertionError("A chat background task must not call Azure")

    pipe = studio.Pipe()
    monkeypatch.setattr(pipe, "_generate", forbidden)
    for task in ("title_generation", "tags_generation", "follow_up_generation"):
        assert await pipe.pipe({}, __task__=task) == ""


@pytest.mark.asyncio
async def test_legacy_request_config_key_reuse():
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        config=SimpleNamespace(IMAGES_OPENAI_API_KEY="legacy-key")
    )))
    assert await studio.Pipe()._key(request=request) == "legacy-key"


@pytest.mark.asyncio
async def test_explicit_environment_key_beats_existing_config(monkeypatch):
    monkeypatch.setenv("TRIPZ_AZURE_FOUNDRY_API_KEY", "shared-env")
    monkeypatch.setenv("TRIPZ_FLUX_API_KEY", "flux-env")
    pipe = fresh_pipe()
    assert await pipe._key() == "shared-env"
    assert await pipe._key(for_flux=True) == "flux-env"


@pytest.mark.asyncio
async def test_sync_legacy_upload_and_urlpath(monkeypatch):
    recorded = {}
    packages = fake_open_webui(monkeypatch, recorded)

    def legacy_upload(request, data, mime, metadata, user):
        return object(), "/api/v1/files/legacy/content"

    packages["open_webui.routers.images"].upload_image = legacy_upload
    intercept_http(monkeypatch, recorded, {"data": [{"b64_json": base64.b64encode(make_img()).decode()}]})
    answer = await render(fresh_pipe())
    assert "/api/v1/files/legacy/content" in answer


@pytest.mark.asyncio
async def test_unknown_models_do_not_fall_back_to_sunburst():
    with pytest.raises(studio.ImageStudioError, match="supported"):
        await studio.Pipe()._generate(model="other", prompt="scene", size="1024x1024", quality="high")


@pytest.mark.asyncio
async def test_attached_files_are_not_silently_ignored():
    with pytest.raises(studio.ImageStudioError, match="editing"):
        await studio.Pipe().pipe({}, __files__=[{"id": "a-reference-image"}])


@pytest.mark.asyncio
async def test_environment_deployment_override(monkeypatch):
    recorded = {}
    monkeypatch.setenv("TRIPZ_SUNBURST_DEPLOYMENT", "my-deployment")
    fake_open_webui(monkeypatch, recorded)
    intercept_http(monkeypatch, recorded, {"data": [{"b64_json": base64.b64encode(make_img()).decode()}]})
    await render(fresh_pipe())
    import json
    assert json.loads(recorded["request"].content)["model"] == "my-deployment"


def test_invalid_images_and_base64_are_rejected():
    with pytest.raises(studio.ImageStudioError, match="base64"):
        studio._decode_b64_image("not-valid-base64!!!!")
    with pytest.raises(studio.ImageStudioError, match="valid image"):
        studio._image_mime(b"not an image")
