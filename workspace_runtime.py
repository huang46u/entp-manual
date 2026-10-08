"""Storage configuration for this portable, source-based deployment."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent


def configure_workspace() -> None:
    if getattr(sys, "frozen", False):
        return
    paths = {
        "TEMP": WORKSPACE / ".runtime" / "tmp",
        "TMP": WORKSPACE / ".runtime" / "tmp",
        "TMPDIR": WORKSPACE / ".runtime" / "tmp",
        "HOME": WORKSPACE / ".runtime" / "home",
        "USERPROFILE": WORKSPACE / ".runtime" / "home",
        "APPDATA": WORKSPACE / ".runtime" / "appdata",
        "LOCALAPPDATA": WORKSPACE / ".runtime" / "localappdata",
        "XDG_CACHE_HOME": WORKSPACE / ".cache",
        "XDG_CONFIG_HOME": WORKSPACE / ".runtime" / "config",
        "XDG_DATA_HOME": WORKSPACE / "data",
        "PIP_CACHE_DIR": WORKSPACE / ".cache" / "pip",
        "UV_CACHE_DIR": WORKSPACE / ".cache" / "uv",
        "PUB_CACHE": WORKSPACE / ".cache" / "pub",
        "FLET_APP_STORAGE_DATA": WORKSPACE / "data",
        "FLET_APP_STORAGE_CACHE": WORKSPACE / ".cache" / "flet",
        "FLET_APP_STORAGE_TEMP": WORKSPACE / ".runtime" / "tmp",
        "PYTHONPYCACHEPREFIX": WORKSPACE / ".cache" / "pycache",
    }
    for name, path in paths.items():
        path.mkdir(parents=True, exist_ok=True)
        os.environ[name] = str(path)
    tempfile.tempdir = str(paths["TEMP"])
    sys.pycache_prefix = str(paths["PYTHONPYCACHEPREFIX"])
    os.environ["PYTHONNOUSERSITE"] = "1"
    # Storage variables alone do not mean the stock client includes Quill.
    os.environ["ENTP_MARKDOWN_EDITOR"] = "plain"
    os.environ["ENTP_WORKSPACE_LOCAL"] = "1"
    for name in ("logs", "backups"):
        (WORKSPACE / "data" / name).mkdir(parents=True, exist_ok=True)
