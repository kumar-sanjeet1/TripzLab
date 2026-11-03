#!/usr/bin/env bash
set -Eeuo pipefail
cd /app/backend
bash start.sh &
webui_pid=$!
stop_webui() {
  kill -TERM "$webui_pid" 2>/dev/null || true
}
trap stop_webui TERM INT EXIT
if ! python /opt/tripz/bootstrap.py; then
  echo "Tripz model installation failed. See the safe error above." >&2
  exit 1
fi
wait "$webui_pid"
