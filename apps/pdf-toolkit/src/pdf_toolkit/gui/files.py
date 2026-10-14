"""Open files with the operating system's default application (no network, no shell)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def open_with_default_app(path: Path) -> None:
    path = Path(path)
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    else:
        subprocess.run(["xdg-open", str(path)], check=False)
