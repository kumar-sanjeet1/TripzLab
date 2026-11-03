"""
title: TripzSearch Azure Image Studio
author: TripzSearch
version: 0.2.0
description: Two selectable Azure Foundry image generators: GPT Image 2.5 Sunburst and FLUX.2 Pro.
requirements: httpx

INSTALL: Open WebUI -> Admin Panel -> Functions -> New Function. Paste this file,
Save, Enable, and configure its admin Valves. Normal users select either model
in the chat model dropdown. Image generation is independent of the default
Open WebUI Images settings.
"""

import base64
import binascii
import inspect
import io
import os
from typing import Literal
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field
from PIL import Image, UnidentifiedImageError


# Configure endpoints with server environment variables or admin Valves.
DEFAULT_SUNBURST_ENDPOINT = ""
DEFAULT_FLUX_ENDPOINT = ""

# All dimensions are divisible by 16 and remain within FLUX.2 Pro's 4 MP limit.
IMAGE_SIZES = (
    "1024x1024",   # square
    "1536x1920",   # Instagram portrait 4:5
    "1536x1024",   # landscape editorial
    "1024x1536",   # portrait editorial
    "1152x2048",   # story / reel 9:16
    "2048x1152",   # YouTube/landscape 16:9
)


class ImageStudioError(Exception):
    """A safe, actionable error appropriate for an end-user message."""


def _safe_endpoint(url: str, expected_path: str) -> str:
    """Restrict admin-configured upstream URLs to Azure HTTPS domains."""
    url = url.strip()
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    allowed = (
        hostname.endswith(".azure.com")
        or hostname.endswith(".cognitive.microsoft.com")
    )
    if not (parsed.scheme == "https" and allowed and parsed.path.endswith(expected_path)):
        raise ImageStudioError(
            "The Azure endpoint is invalid. Check the full HTTPS URL in the Pipe admin Valves."
        )
    if parsed.username or parsed.password or parsed.fragment:
        raise ImageStudioError("The Azure endpoint contains unsupported URL components.")
    return url


def _last_user_prompt(messages: list) -> str:
    """Use the actual user prompt; don't send the whole chat transcript to images APIs."""
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content", "")
        if isinstance(content, str):
            prompt = content
        elif isinstance(content, list):
            prompt = "\n".join(
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            )
            if any(
                isinstance(item, dict) and item.get("type") in ("image_url", "image")
                for item in content
            ):
                raise ImageStudioError(
                    "This version generates new images from text. Reference-image editing is not enabled yet."
                )
        else:
            continue
        prompt = prompt.strip()
        if not prompt:
            raise ImageStudioError("Enter an image description before pressing Send.")
        if len(prompt) > 32000:
            raise ImageStudioError("The prompt is too long (maximum 32,000 characters).")
        return prompt
    raise ImageStudioError("Enter an image description before pressing Send.")


def _find_image_result(response_json: dict) -> tuple[str, str]:
    """Handle common Azure/OpenAI/BFL image response variants without guessing."""
    if not isinstance(response_json, dict):
        raise ImageStudioError("Azure returned an unexpected non-object response.")

    items = response_json.get("data") or response_json.get("images")
    if isinstance(items, list) and items:
        candidate = items[0]
    else:
        candidate = response_json.get("result", response_json)

    if isinstance(candidate, list) and candidate:
        candidate = candidate[0]

    if isinstance(candidate, str):
        if candidate.startswith("https://"):
            return "url", candidate
        if candidate.startswith("data:image/"):
            return "base64", candidate

    if not isinstance(candidate, dict):
        raise ImageStudioError("Azure did not return a recognizable image result.")

    for key in ("b64_json", "base64", "image_base64"):
        value = candidate.get(key)
        if isinstance(value, str) and value:
            return "base64", value

    for key in ("url", "image_url", "sample"):
        value = candidate.get(key)
        if isinstance(value, str) and value:
            if value.startswith("data:image/"):
                return "base64", value
            if value.startswith("https://"):
                return "url", value

    # Some BFL-compatible responses wrap a single image in result.image.
    inner = candidate.get("image")
    if isinstance(inner, dict):
        return _find_image_result(inner)
    if isinstance(inner, str) and inner:
        if inner.startswith("https://"):
            return "url", inner
        return "base64", inner
    raise ImageStudioError(
        "Azure returned no supported image field. Compare the response format with Foundry's View Code tab."
    )


def _decode_b64_image(encoded: str) -> bytes:
    if encoded.startswith("data:image/"):
        encoded = encoded.split(",", 1)[-1]
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise ImageStudioError("Azure returned invalid base64 image data.") from None
    if len(decoded) > 32 * 1024 * 1024:
        raise ImageStudioError("Azure returned an image larger than 32 MB.")
    return decoded


def _image_mime(data: bytes) -> str:
    """Validate bytes and infer actual MIME, rather than trusting the API field."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
        with Image.open(io.BytesIO(data)) as im:
            fmt = (im.format or "").upper()
    except (UnidentifiedImageError, OSError, ValueError):
        raise ImageStudioError("Azure returned data that is not a valid image.") from None
    mapping = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
    if fmt not in mapping:
        raise ImageStudioError("Azure returned an unsupported image format.")
    return mapping[fmt]


class Pipe:
    """Two Azure Foundry image models, exposed in the normal Open WebUI selector."""

    class Valves(BaseModel):
        SUNBURST_ENDPOINT: str = Field(
            default=DEFAULT_SUNBURST_ENDPOINT,
            description="Full Azure /openai/v1/images/generations URL (not just the base URL).",
        )
        SUNBURST_DEPLOYMENT: str = Field(
            default="gpt-image-2.5-sunburst",
            description="Exact Azure deployment name, not necessarily the catalog model name.",
        )
        FLUX_ENDPOINT: str = Field(
            default=DEFAULT_FLUX_ENDPOINT,
            description="Full BFL /providers/blackforestlabs/v1/flux-2-pro?api-version=preview URL from Foundry View Code.",
        )
        FLUX_MODEL: str = Field(
            default="FLUX.2-pro",
            description="FLUX model ID in the provider-specific JSON request.",
        )
        SHARED_AZURE_KEY: str = Field(
            default="",
            description="Azure Foundry resource key. Prefer the TRIPZ_AZURE_FOUNDRY_API_KEY server secret instead of saving this field.",
            json_schema_extra={"input": {"type": "password"}},
        )
        FLUX_AZURE_KEY: str = Field(
            default="",
            description="Optional separate FLUX key; leave empty to reuse the same Azure resource key.",
            json_schema_extra={"input": {"type": "password"}},
        )

    class UserValves(BaseModel):
        IMAGE_SIZE: Literal[
            "1024x1024", "1536x1920", "1536x1024",
            "1024x1536", "1152x2048", "2048x1152"
        ] = Field(
            default="1536x1920",
            description="Image dimensions. 1536x1920 is ideal for Instagram feed (4:5).",
        )
        SUNBURST_QUALITY: Literal["high", "xhigh", "max"] = Field(
            default="xhigh",
            description="Sunburst quality. max can be slower and more expensive.",
        )

    def __init__(self):
        self.valves = self.Valves()

    def pipes(self):
        # These IDs are fixed and human-readable in the chat model selector.
        return [
            {"id": "sunburst", "name": "Tripz Image - GPT Image 2.5 Sunburst"},
            {"id": "flux", "name": "Tripz Image - FLUX.2 Pro"},
        ]

    async def _key(self, for_flux: bool = False, request=None) -> str:
        """Environment > optional dedicated key > shared valve > existing Images key."""
        specific_env = "TRIPZ_FLUX_API_KEY" if for_flux else "TRIPZ_SUNBURST_API_KEY"
        value = os.getenv(specific_env, "").strip()
        if value:
            return value
        if for_flux:
            value = self.valves.FLUX_AZURE_KEY.strip()
            if value:
                return value
        value = os.getenv("TRIPZ_AZURE_FOUNDRY_API_KEY", "").strip()
        if value:
            return value
        value = self.valves.SHARED_AZURE_KEY.strip()
        if value:
            return value
        # Open WebUI <=0.12 keeps the resolved config on the request's app.
        config = getattr(getattr(getattr(request, "app", None), "state", None), "config", None)
        existing = getattr(config, "IMAGES_OPENAI_API_KEY", None)
        if isinstance(existing, str) and existing.strip():
            return existing.strip()
        try:
            # Reuse the key already saved on Admin -> Settings -> Images.
            from open_webui.models.config import Config

            existing = Config.get("image_generation.openai.api_key")
            if inspect.isawaitable(existing):
                existing = await existing
            if isinstance(existing, str) and existing.strip():
                return existing.strip()
        except (ImportError, AttributeError):
            pass
        raise ImageStudioError(
            "No Azure key configured. Set TRIPZ_AZURE_FOUNDRY_API_KEY on the server "
            "or set SHARED_AZURE_KEY in this Pipe's admin Valves."
        )

    async def _generate(self, *, model: str, prompt: str, size: str, quality: str, request=None):
        if model not in {"sunburst", "flux"}:
            raise ImageStudioError("Select a supported Tripz Image model.")
        if size not in IMAGE_SIZES:
            raise ImageStudioError("Unsupported size; choose a preset in the model's Valves.")
        width, height = map(int, size.split("x"))
        is_flux = model == "flux"
        url = _safe_endpoint(
            os.getenv("TRIPZ_FLUX_ENDPOINT", self.valves.FLUX_ENDPOINT)
            if is_flux else os.getenv("TRIPZ_SUNBURST_ENDPOINT", self.valves.SUNBURST_ENDPOINT),
            "/providers/blackforestlabs/v1/flux-2-pro" if is_flux else "/openai/v1/images/generations",
        )
        key = await self._key(for_flux=is_flux, request=request)
        if is_flux:
            payload = {
                "model": os.getenv("TRIPZ_FLUX_MODEL", self.valves.FLUX_MODEL),
                "prompt": prompt,
                "width": width,
                "height": height,
                "num_images": 1,
                "output_format": "jpeg",
            }
        else:
            payload = {
                "model": os.getenv("TRIPZ_SUNBURST_DEPLOYMENT", self.valves.SUNBURST_DEPLOYMENT),
                "prompt": prompt,
                "size": size,
                "n": 1,
                "quality": quality,
                "output_format": "png",
            }
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(240.0, connect=20.0), follow_redirects=False
            ) as client:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json=payload,
                )
                if response.status_code >= 400:
                    self._raise_http_error(response.status_code, is_flux)
                if response.status_code >= 300:
                    raise ImageStudioError("Azure returned an unexpected redirect; verify the endpoint URL.")
                result = response.json()
        except httpx.TimeoutException:
            raise ImageStudioError("Azure image request timed out. Try again or select a smaller size.") from None
        except httpx.RequestError:
            raise ImageStudioError("Could not reach Azure. Check network access and the endpoint.") from None
        except ValueError:
            raise ImageStudioError("Azure returned an invalid JSON response.") from None
        return _find_image_result(result)

    @staticmethod
    def _raise_http_error(status: int, is_flux: bool):
        model = "FLUX.2 Pro" if is_flux else "Sunburst"
        if status in (401, 403):
            raise ImageStudioError(f"Azure rejected {model} authentication/permissions (HTTP {status}). Check its key and deployment access.")
        if status == 404:
            raise ImageStudioError(f"Azure did not find the {model} deployment/endpoint (HTTP 404). Verify the exact Foundry endpoint and deployment name.")
        if status == 429:
            raise ImageStudioError(f"Azure rate limit reached for {model} (HTTP 429). Try again after the service limit resets.")
        if status == 400:
            raise ImageStudioError(f"Azure rejected {model} parameters (HTTP 400). Compare the deployment settings, dimensions and API schema in Foundry View Code.")
        raise ImageStudioError(f"Azure {model} generation failed (HTTP {status}). Check your Foundry deployment status.")

    @staticmethod
    async def _emit(emitter, message: str, done: bool):
        if emitter is None:
            return
        try:
            await emitter({"type": "status", "data": {"description": message, "done": done}})
        except Exception:
            # Status notifications must not prevent image generation.
            pass

    async def pipe(
        self,
        body: dict,
        __user__: dict = None,
        __request__=None,
        __chat_id__: str = None,
        __message_id__: str = None,
        __event_emitter__=None,
        __task__: str = None,
        __files__: list = None,
    ) -> str:
        """Render and store an image in the user's Open WebUI files/chat."""
        # Title, tag and follow-up generation are not image requests.
        if __task__:
            return ""
        if __files__:
            raise ImageStudioError(
                "This version generates new images from text. Reference-image editing is not enabled yet."
            )
        model_id = str(body.get("model", ""))
        model_suffix = model_id.rsplit(".", 1)[-1]
        if model_suffix not in {"sunburst", "flux"}:
            raise ImageStudioError("Please select Tripz Image - Sunburst or Tripz Image - FLUX.2 Pro.")
        prompt = _last_user_prompt(body.get("messages") or [])
        user_valves = (__user__ or {}).get("valves") if isinstance(__user__, dict) else None
        if isinstance(user_valves, self.UserValves):
            options = user_valves
        elif isinstance(user_valves, dict):
            options = self.UserValves(**user_valves)
        elif hasattr(user_valves, "model_dump"):
            options = self.UserValves(**user_valves.model_dump())
        else:
            options = self.UserValves()

        if (
            not __user__ or not isinstance(__user__, dict)
            or not __user__.get("id") or __request__ is None
        ):
            raise ImageStudioError(
                "Open WebUI did not provide a logged-in user/request. "
                "Use this model in a normal signed-in chat."
            )

        label = "FLUX.2 Pro" if model_suffix == "flux" else "GPT Image 2.5 Sunburst"
        await self._emit(__event_emitter__, f"Generating with {label} at {options.IMAGE_SIZE}...", False)
        try:
            kind, image_value = await self._generate(
                model=model_suffix,
                prompt=prompt,
                size=options.IMAGE_SIZE,
                quality=options.SUNBURST_QUALITY,
                request=__request__,
            )
            if kind == "base64":
                data = _decode_b64_image(image_value)
            else:
                # Use Open WebUI's SSRF-aware image fetch for provider-hosted URLs.
                from open_webui.routers.images import get_image_data

                fetched = get_image_data(image_value)
                if inspect.isawaitable(fetched):
                    fetched = await fetched
                data, _ = fetched
                if data is None:
                    raise ImageStudioError("Azure returned an image URL that could not be downloaded safely.")
            if len(data) > 32 * 1024 * 1024:
                raise ImageStudioError("Image exceeds the 32 MB safety limit.")
            content_type = _image_mime(data)
            from open_webui.models.users import Users
            from open_webui.routers.images import upload_image

            user = Users.get_user_by_id(__user__["id"])
            if inspect.isawaitable(user):
                user = await user
            if user is None:
                raise ImageStudioError("Could not resolve your Open WebUI user account.")

            with Image.open(io.BytesIO(data)) as generated:
                actual_size = f"{generated.width}x{generated.height}"
            metadata = {"model": label, "size": actual_size, "requested_size": options.IMAGE_SIZE,
                        "prompt": prompt, "source": "tripz_image_studio"}
            if __chat_id__ and __message_id__:
                metadata.update({"chat_id": __chat_id__, "message_id": __message_id__})
            saved = upload_image(
                __request__, data, content_type, metadata, user,
            )
            if inspect.isawaitable(saved):
                saved = await saved
            _, stored = saved
            # Older versions return a URLPath; newer versions return a file dict.
            image_url = str(stored["url"] if isinstance(stored, dict) else stored)
            if not image_url.startswith("/") or image_url.startswith("//"):
                raise ImageStudioError("Open WebUI did not return a usable local image URL.")

            await self._emit(__event_emitter__, f"Image generated with {label}", True)
            quality_note = f" · {options.SUNBURST_QUALITY}" if model_suffix == "sunburst" else ""
            return (
                f"**{label}** · {actual_size}{quality_note}\n\n"
                f"![Generated with {label}]({image_url})\n\n"
                f"[Download original image]({image_url}?attachment=true)"
            )
        except ImageStudioError as exc:
            await self._emit(__event_emitter__, "Generation failed", True)
            raise exc
        except Exception:
            await self._emit(__event_emitter__, "Generation failed", True)
            # Don't return stack traces, bearer tokens or potentially signed URLs to users.
            raise ImageStudioError(
                "Image generation could not finish or save the result. Check Open WebUI backend logs."
            ) from None
