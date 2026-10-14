"""Module registry. Each feature of the toolkit (redaction today; pdf2md, translation later) is a
module discovered through the ``pdf_toolkit.modules`` entry point group, so separate packages,
including closed-source ones, can plug into the same CLI and GUI shell::

    [project.entry-points."pdf_toolkit.modules"]
    mymodule = "my_package.module:MODULE"
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Any

ENTRY_POINT_GROUP = "pdf_toolkit.modules"


@dataclass(frozen=True)
class ToolkitModule:
    name: str
    title: str
    # add_cli(subparsers) registers a sub-command; handlers have signature handler(args, cfg) -> int
    add_cli: Callable[[argparse._SubParsersAction], None]
    # create_tab(parent_widget, cfg) -> tkinter widget, or None for CLI-only modules
    create_tab: Callable[[Any, Any], Any] | None = None


def discover() -> list[ToolkitModule]:
    modules = [ep.load() for ep in entry_points(group=ENTRY_POINT_GROUP)]
    return sorted(modules, key=lambda m: m.name)
