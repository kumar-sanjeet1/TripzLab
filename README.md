# TripzLab

TripzSearch's creative workspace, built on Open WebUI with Azure Foundry image models and an optional general chat connection:

- **Tripz Image - GPT Image 2.5 Sunburst**
- **Tripz Image - FLUX.2 Pro**

Select a model in the normal chat dropdown, describe an image, and download the
original. No separate chat model or Image Generation toggle is required.
Resolution is configurable through the model's User Valves; the default is
Instagram portrait (`1536x1920`). Sunburst defaults to `xhigh` quality.

Each model calls its own Azure API. The Pipe uses the latest user prompt directly,
skips background title/tag requests, validates image bytes, and saves the original
to the signed-in user's Open WebUI storage. Generated messages show the actual
output dimensions. Sunburst supports both new images and reference-image edits.

## Reference images and follow-up edits

Select **Tripz Image - GPT Image 2.5 Sunburst**, attach PNG, JPEG, or WebP images,
and describe what to change. Explicit references use Azure's image-edit API.
You can upload up to 16 reference images (32 MB each, 64 MB total).

For follow-up edits without another upload, Sunburst reuses the last generated
image in the chat. Start a new chat or disable **USE_PREVIOUS_IMAGE** in User
Valves for independent generations. The original preview/download flow is kept.
Reference editing is currently wired for Sunburst; the FLUX option generates new
images from text.

## General chat

Set `TRIPZ_CHAT_AUTO_SETUP=true` to add a native Azure text-model connection. It
uses the shared Azure resource key, or `TRIPZ_CHAT_API_KEY` for a separate resource.
`TRIPZ_CHAT_BASE_URL` defaults to the image resource's `/openai/v1` base URL.

Set `TRIPZ_CHAT_DEPLOYMENT` to the exact Azure text deployment name. If omitted,
setup checks Azure's model list and prefers a GPT Sol model when one is listed.
The candidate must answer a test request through Open WebUI before it is kept.
A failed test restores the previous connection configuration.

The text model appears as **tripz-chat.<deployment>** in the ordinary selector.
Use it for captions, scripts, prompt writing, and general assistance. Image
models stay separately selectable. Existing provider connections are preserved.

## Railway

Railway builds the root Dockerfile, which extends the official Open WebUI
`v0.12.5` image. The startup importer installs the bundled Pipe through the local
authenticated Functions API. Source updates are backed up on the persistent data
volume and unrelated Functions and Valve settings are preserved.

1. Connect this repository's `main` branch to a Railway service.
2. Attach a persistent volume at `/app/backend/data`.
3. Set the required service variables below.
4. Deploy, open the service URL, and sign in with the bootstrap admin account.
5. Verify both image models, then create ordinary team accounts through the Admin Panel.

| Variable | Purpose |
| --- | --- |
| `WEBUI_SECRET_KEY` | Stable random app/encryption secret; retain it with the volume |
| `WEBUI_ADMIN_EMAIL` | Initial owner account |
| `WEBUI_ADMIN_PASSWORD` | Strong initial admin password |
| `TRIPZ_AZURE_FOUNDRY_API_KEY` | Shared Azure resource key, or use the per-model variables |
| `TRIPZ_SUNBURST_ENDPOINT` | Full Azure URL ending in `/openai/v1/images/generations` |
| `TRIPZ_FLUX_ENDPOINT` | Full Azure URL ending in `/providers/blackforestlabs/v1/flux-2-pro?api-version=preview` |

Optional: `TRIPZ_SUNBURST_API_KEY`, `TRIPZ_FLUX_API_KEY`,
`TRIPZ_SUNBURST_DEPLOYMENT`, and `TRIPZ_FLUX_MODEL`. Deployment/model names must
match Foundry. See `.env.example` and [DEPLOYMENT.md](DEPLOYMENT.md).

Signups are disabled. Azure credentials remain on the backend. Automatic model-import failures are logged without stopping Open WebUI.
`WEBUI_ADMIN_EMAIL` and `WEBUI_ADMIN_PASSWORD` initialize a fresh database; changing
these variables does not change an existing account. Change a saved password from
the account settings while signed in. Bootstrap admin
credentials must match the saved account for subsequent automatic imports. For
MFA, use `TRIPZ_BOOTSTRAP_ADMIN_TOKEN`. To remove bootstrap credentials after
installation, first set `TRIPZ_AUTO_INSTALL=false`; later source updates will
require an authenticated import.

## Local development

For a fresh installation alongside an existing Open WebUI on port 8080:

```bash
cp .env.example .env
# Fill .env locally, including the endpoints and secrets.
docker compose up --build -d
```

Open `http://localhost:8081`. This uses a dedicated data volume.

To install only the Pipe into an existing instance:

```bash
python3 install_local.py
```

It prompts for local administrator credentials without saving them. Configure
the two endpoints and keys in the Function's admin Valves or server environment.
Use `--update` to back up and replace an existing copy.

## Verification

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
python3 smoke_test.py --url http://localhost:8081 --generate
```

Automated tests simulate provider responses. The smoke test makes one real Azure
request per model and downloads the originals; it uses Azure quota. Check prompt
fidelity, previews, refresh persistence, and ordinary-user access in the UI too.

Open WebUI is distributed under its upstream license. Its branding and login are
retained by this deployment. See the [upstream project](https://github.com/open-webui/open-webui).
