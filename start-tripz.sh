#!/usr/bin/env bash
set -Eeuo pipefail
tripz_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "${TRIPZ_BACKEND_DIR:-/app/backend}"
bash start.sh &
webui_pid=$!
stop_webui() {
  kill -TERM "$webui_pid" 2>/dev/null || true
}
trap stop_webui TERM INT EXIT
if ! python "$tripz_dir/bootstrap.py"; then
  echo "Tripz automatic model import failed. Open WebUI remains running; sign in as an administrator to repair the import. Existing models and data are retained." >&2
fi
wait "$webui_pid"
