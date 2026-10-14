"""Redaction engines: one object per file family, discovered through entry points.

Third-party packages can add engines (for example a PyMuPDF-based PDF engine under its own
license) by declaring, in their ``pyproject.toml``::

    [project.entry-points."pdf_toolkit.redaction_engines"]
    myengine = "my_package.engine:MyEngine"

An engine class is built with ``Engine(settings: dict)`` where ``settings`` is the engine's table
from the app configuration (``[engines.<name>]``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib.metadata import entry_points
from pathlib import Path
from typing import Protocol, runtime_checkable

from pdf_redaction.rules.context import RedactionContext

ENTRY_POINT_GROUP = "pdf_toolkit.redaction_engines"


class EngineError(RuntimeError):
    """Raised by engines. The message must never contain document content or redaction terms."""


@dataclass
class EngineResult:
    counts: dict[str, int] = field(default_factory=dict)  # rule label -> replacements, when known
    remote_calls: int = 0  # requests made to an external engine (e.g. Stirling quota)


@runtime_checkable
class Engine(Protocol):
    name: str
    version: str
    suffixes: frozenset[str]

    def redact(self, src: Path, dst: Path, ctx: RedactionContext) -> EngineResult: ...


def load_engines(settings: dict[str, dict] | None = None, enabled: list[str] | None = None) -> dict[str, Engine]:
    """Instantiate engines by entry-point name. ``enabled`` keeps order = priority."""
    settings = settings or {}
    found = {ep.name: ep for ep in entry_points(group=ENTRY_POINT_GROUP)}
    names = enabled if enabled is not None else sorted(found)
    engines: dict[str, Engine] = {}
    for name in names:
        if name not in found:
            raise EngineError(f"redaction engine not installed: {name}")
        engines[name] = found[name].load()(settings.get(name, {}))
    return engines


def engine_for(path: Path, engines: dict[str, Engine]) -> Engine | None:
    suffix = Path(path).suffix.lower()
    for engine in engines.values():
        if suffix in engine.suffixes:
            return engine
    return None
