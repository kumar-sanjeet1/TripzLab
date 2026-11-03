# TripzSearch Image Studio - staging preparation

Deployment procedures for the TripzLab repository. Verify the release gate below for every target environment.

The Docker build uses the official Open WebUI `v0.12.5` image. Before staging,
record the version of the working local instance and use the same version if
different. Do not upgrade an existing data volume as part of this setup without
a backup. The integration leaves Open WebUI's own branding and login intact.

## Existing local installation

Install `tripz_image_studio.py` into the running instance using `install_local.py`
or its Admin Panel. There is no need to replace your app or its database.
The function exposes two models in the ordinary model selector. Keep the separate
Image Generation tool off for these models. Azure keys stay on the server.

## Reproducible fresh local container

Docker is required for this optional clean install. It uses **port 8081** and a
new volume, so it can be tested alongside the existing instance on port 8080.

1. Copy `.env.example` to `.env` and enter the Azure key and bootstrap admin credentials.
2. Generate one stable `WEBUI_SECRET_KEY`, for example with `python3 -c 'import secrets; print(secrets.token_hex(32))'`.
3. Run `docker compose up --build -d`.
4. Open `http://localhost:8081`, sign in, and verify both Tripz Image models.
5. Run `python3 smoke_test.py --url http://localhost:8081 --generate` on this computer.

The bootstrap process signs in to the local backend and installs/enables the Pipe
through its authenticated API. Repeated starts retain the same Function when its
source matches; changed source is backed up under the persistent data directory.
It preserves unrelated functions and stored Valve settings. It never prints keys.

## Railway staging, after local checks pass

Use a dedicated staging service. Railway detects the root Dockerfile automatically.
Configure the service health check as `/health` with a 300-second timeout, one
replica, and at most three restart attempts. Required service settings:

| Setting | Value |
| --- | --- |
| Persistent volume mount | `/app/backend/data` |
| `WEBUI_SECRET_KEY` | Stable random secret, retained with the volume |
| `WEBUI_ADMIN_EMAIL` | Owner's initial admin email |
| `WEBUI_ADMIN_PASSWORD` | Initial admin password, entered as a service secret |
| `TRIPZ_AZURE_FOUNDRY_API_KEY` | Shared Azure resource key, or use separate per-model variables |
| `TRIPZ_AUTO_INSTALL` | `true` while the image imports its bundled Pipe |
| `ENABLE_SIGNUP` | `false` |
| `DEFAULT_USER_ROLE` | `pending` |
| `ENABLE_VALVE_ENCRYPTION` | `true` |
| `DATA_DIR` | `/app/backend/data` |
| `PORT` | Supplied by Railway; don't override unless needed |

Endpoint and deployment overrides are documented in `.env.example`.
Use environment variables for Azure credentials rather than storing keys in source
or image layers. `.dockerignore` excludes local secret files and test outputs.

On a fresh volume, Open WebUI creates the initial admin from its bootstrap
credentials. For an existing instance with MFA, use a short-lived admin token in
`TRIPZ_BOOTSTRAP_ADMIN_TOKEN` for import instead. After import, you can set
`TRIPZ_AUTO_INSTALL=false` and remove bootstrap credentials. Future image source
updates then require another authenticated import; the saved Pipe remains in the
database in the meantime.

Don't copy the desktop database into staging by default. Create the team member's
ordinary account through the Admin Panel after checking the admin flow. Validate
model access and downloads as that user before sharing the URL.

## Release gate

- Generate the same travel prompt once with each actual Azure deployment.
- Check prompt fidelity, selected provider, actual dimensions, preview, and original download.
- Refresh the chat and confirm the saved images still display.
- Confirm a normal team account can generate and download, and cannot see admin secrets.
- Restart the service and confirm its users, Function, chats, and images persist.
- Observe Railway's terminal `SUCCESS` deployment status and a healthy HTTP response.

Rollback: retain the prior container version and the pre-change volume backup.
Don't delete the data volume to fix a deployment failure.

## Evidence and limits

Automated tests cover request routing, format isolation, key precedence, older
helper compatibility, auxiliary-task suppression, error handling, installer
guards, and bootstrap idempotence. These use simulated Azure/Open WebUI responses.
They do not prove either deployment works with the resource's real credentials.
The local workspace has no Docker daemon; verify the actual image build and
runtime through the target Railway deployment. Record deployment verification separately from provider-generation verification. Azure credentials are configured in the service environment.

Official references:

- https://docs.openwebui.com/features/extensibility/plugin/functions/pipe/
- https://docs.openwebui.com/reference/env-configuration/
- https://docs.openwebui.com/features/extensibility/plugin/development/valves/
- https://learn.microsoft.com/en-us/azure/foundry/reference/rest/images-create-image
- https://learn.microsoft.com/en-us/azure/foundry/foundry-models/how-to/use-foundry-models-flux
- https://docs.railway.com/deployments/volumes
