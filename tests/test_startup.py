import os
from pathlib import Path
import subprocess

import pytest


@pytest.mark.parametrize("import_status,app_status", [(0, 0), (1, 0), (0, 7)])
def test_import_failure_does_not_stop_webui(tmp_path, import_status, app_status):
    backend = tmp_path / "backend"
    backend.mkdir()
    (backend / "start.sh").write_text(f"#!/usr/bin/env bash\necho webui-started\nsleep 0.15\nexit {app_status}\n")
    commands = tmp_path / "bin"
    commands.mkdir()
    python = commands / "python"
    python.write_text(f"#!/usr/bin/env bash\nexit {import_status}\n")
    python.chmod(0o700)
    env = {**os.environ, "TRIPZ_BACKEND_DIR": str(backend), "PATH": str(commands) + os.pathsep + os.environ["PATH"]}
    script = Path(__file__).resolve().parents[1] / "start-tripz.sh"
    result = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=5)
    assert result.returncode == app_status
    assert "webui-started" in result.stdout
    if import_status:
        assert "Open WebUI remains running" in result.stderr
