from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

from workspace_runtime import configure_workspace

configure_workspace()

ROOT = Path(__file__).resolve().parent
LOGS = ROOT / "data" / "logs"


def emergency_log(message: str) -> None:
    try:
        LOGS.mkdir(parents=True, exist_ok=True)
        with (LOGS / "flet-crash.log").open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message.rstrip()}\n")
    except OSError:
        pass


try:
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    import flet_app

    flet_app.main()
except BaseException:
    emergency_log("Flet windowless launcher failure\n" + traceback.format_exc())
    raise
