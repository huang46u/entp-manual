from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class WorkspaceStorageTests(unittest.TestCase):
    def test_direct_entry_overrides_inherited_storage_outside_workspace(self) -> None:
        root = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        for name in (
            "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE", "APPDATA",
            "LOCALAPPDATA", "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME",
            "PIP_CACHE_DIR", "UV_CACHE_DIR", "PUB_CACHE", "FLET_APP_STORAGE_DATA",
            "FLET_APP_STORAGE_CACHE", "FLET_APP_STORAGE_TEMP",
        ):
            env[name] = str(root.parent / "unrelated-storage")
        # Python starts with a safe bytecode path before importing the bootstrap.
        env["PYTHONPYCACHEPREFIX"] = str(root / ".cache" / "pycache")
        code = """
import os, sys, tempfile
from pathlib import Path
from workspace_runtime import configure_workspace, WORKSPACE
configure_workspace()
import flet_app
keys = ('TEMP', 'TMP', 'TMPDIR', 'HOME', 'USERPROFILE', 'APPDATA',
        'LOCALAPPDATA', 'XDG_CACHE_HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME',
        'PIP_CACHE_DIR', 'UV_CACHE_DIR', 'PUB_CACHE', 'FLET_APP_STORAGE_DATA',
        'FLET_APP_STORAGE_CACHE', 'FLET_APP_STORAGE_TEMP', 'PYTHONPYCACHEPREFIX')
for key in keys:
    assert Path(os.environ[key]).resolve().is_relative_to(WORKSPACE), key
assert Path(tempfile.gettempdir()).is_relative_to(WORKSPACE)
assert Path.home().is_relative_to(WORKSPACE)
assert Path(sys.pycache_prefix).is_relative_to(WORKSPACE)
assert flet_app.DEFAULT_DB == WORKSPACE / 'data' / 'entp_manual.db'
assert not flet_app.native_quill_available()
with tempfile.NamedTemporaryFile() as probe:
    assert Path(probe.name).is_relative_to(WORKSPACE)
"""
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=root, env=env,
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
