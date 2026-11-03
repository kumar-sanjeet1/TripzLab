"""Register a verified Azure text model as a native Open WebUI connection.

Runs on the server. Credentials stay in process and the admin-only provider
configuration. A failed probe restores the previous connection configuration.
"""
import copy
import json
import os
import re
from urllib import error, parse, request

from install_local import InstallationError, api_call


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def chat_base_url():
    url = os.getenv("TRIPZ_CHAT_BASE_URL", "").strip().rstrip("/")
    if not url:
        endpoint = os.getenv("TRIPZ_SUNBURST_ENDPOINT", "").strip()
        parsed = parse.urlparse(endpoint)
        if not parsed.path.endswith("/images/generations"):
            raise InstallationError("Set TRIPZ_CHAT_BASE_URL to the Azure /openai/v1 URL.")
        url = parsed._replace(path=parsed.path.removesuffix("/images/generations"), query="", fragment="").geturl()
    parsed = parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if (parsed.scheme != "https" or not (host.endswith(".azure.com") or host.endswith(".cognitive.microsoft.com"))
            or not parsed.path.endswith("/openai/v1") or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise InstallationError("The text-model endpoint must be an Azure HTTPS /openai/v1 URL.")
    return url


def choose_model(models, explicit=""):
    if explicit.strip():
        return explicit.strip()
    ids = [m.get("id", "") for m in models if isinstance(m, dict) and isinstance(m.get("id"), str)]
    excluded = ("image", "flux", "dall-e", "embed", "whisper", "audio", "speech", "tts", "realtime", "transcri")
    candidates = [name for name in ids if ("gpt" in name.lower() or "sol" in name.lower())
                  and not any(word in name.lower() for word in excluded)]
    if not candidates:
        raise InstallationError("No text model was listed by Azure. Set TRIPZ_CHAT_DEPLOYMENT to your deployed chat model name.")
    return max(candidates, key=lambda name: (
        name.lower() == "gpt-sol", "sol" in name.lower(),
        tuple(map(int, re.findall(r"\d+", name))), "preview" not in name.lower(), name,
    ))


def connection_config(previous, url, key, model):
    result = copy.deepcopy(previous)
    urls = list(result.get("OPENAI_API_BASE_URLS") or [])
    keys = list(result.get("OPENAI_API_KEYS") or [])
    keys += [""] * max(0, len(urls) - len(keys))
    configs = dict(result.get("OPENAI_API_CONFIGS") or {})
    match = next((i for i, value in enumerate(urls) if value.rstrip("/") == url
                  and configs.get(str(i), {}).get("prefix_id") == "tripz-chat"), None)
    if match is None:
        match = len(urls)
        urls.append(url)
        keys.append(key)
    else:
        keys[match] = key
    for index, value in enumerate(urls):
        # Disable only Open WebUI's unused, keyless default placeholder.
        if value.rstrip("/") == "https://api.openai.com/v1" and not keys[index] and not configs.get(str(index)):
            configs[str(index)] = {"enable": False}
    configs[str(match)] = {**configs.get(str(match), {}), "enable": True, "provider": "azure", "azure": True,
                           "api_type": "responses", "prefix_id": "tripz-chat", "model_ids": [model]}
    return {"ENABLE_OPENAI_API": True, "OPENAI_API_BASE_URLS": urls, "OPENAI_API_KEYS": keys[:len(urls)], "OPENAI_API_CONFIGS": configs}


def setup_chat(base, token):
    url = chat_base_url()
    key = os.getenv("TRIPZ_CHAT_API_KEY", "").strip() or os.getenv("TRIPZ_AZURE_FOUNDRY_API_KEY", "").strip()
    if not key:
        raise InstallationError("Set TRIPZ_CHAT_API_KEY or the shared Azure resource key to enable general chat.")
    explicit = os.getenv("TRIPZ_CHAT_DEPLOYMENT", "").strip()
    models = []
    if not explicit:
        req = request.Request(url + "/models", headers={"api-key": key, "Accept": "application/json"})
        try:
            with request.build_opener(NoRedirect()).open(req, timeout=25) as response:
                models = json.load(response).get("data", [])
        except (error.URLError, ValueError, AttributeError):
            raise InstallationError("Azure model discovery was unavailable. Set TRIPZ_CHAT_DEPLOYMENT to the exact deployed text model name.") from None
    if not explicit:
        names = [m.get("id", "") for m in models if isinstance(m, dict)]
        print("Tripz Azure model discovery: " + ", ".join(str(name) for name in names[:20]))
    model = choose_model(models, explicit)
    previous = api_call(base, token, "GET", "/openai/config")
    updated = connection_config(previous, url, key, model)
    api_call(base, token, "POST", "/openai/config/update", updated)
    try:
        response = api_call(base, token, "POST", "/api/chat/completions", {
            "model": "tripz-chat." + model, "stream": False,
            "messages": [{"role": "user", "content": "Reply with the single word READY."}],
            "max_tokens": 1024,
        }, timeout=120)
        content = response["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise InstallationError("The text model returned no reply during verification.")
    except Exception:
        api_call(base, token, "POST", "/openai/config/update", previous)
        raise InstallationError(
            f"Azure text deployment '{model}' could not answer through Open WebUI. "
            "Previous connections were restored. Set TRIPZ_CHAT_DEPLOYMENT to the actual Azure chat deployment name."
        ) from None
    print(f"Tripz chat ready: tripz-chat.{model} (reply verified through Open WebUI).")
    return model
