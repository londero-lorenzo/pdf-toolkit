"""User configuration, kept outside the repository.

Location: ``$PDF_TOOLKIT_CONFIG`` if set, else ``%APPDATA%/pdf-toolkit/config.toml`` on Windows and
``~/.config/pdf-toolkit/config.toml`` elsewhere. ``pdf-toolkit config init`` writes a template.
"""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

TEMPLATE = """\
# pdf-toolkit configuration. This file is personal: never commit it.

[redaction]
# Files with one term per line, applied to every folder (in addition to <folder>/.redaction/terms.txt)
global_term_files = []
# CSV files "real,alias": the real value is replaced by the alias
global_alias_files = []
# Built-in PII pattern packs: "common", "it"
pattern_packs = ["common"]
# Where private workspaces (copies of the originals) are created
workspace_root = ""
# Optional default for "publish": <output_root>/<alias>, used until the session has a destination.
# "publish --to FOLDER" overrides it and is remembered for that session.
output_root = ""
# Folders where unredacted data must never land (synced, shared, read by other tools...)
protected_locations = []
# Engines in priority order
engines = ["stirling", "text"]
workers = 3

[engines.stirling]
url = "http://127.0.0.1:8080"
api_key_file = ""
endpoint = "auto-redact"
sanitize = true
timeout_seconds = 300
"""


def default_path() -> Path:
    if env := os.environ.get("PDF_TOOLKIT_CONFIG"):
        return Path(env)
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "pdf-toolkit" / "config.toml"
    return Path.home() / ".config" / "pdf-toolkit" / "config.toml"


@dataclass
class RedactionConfig:
    global_term_files: list[Path] = field(default_factory=list)
    global_alias_files: list[Path] = field(default_factory=list)
    pattern_packs: list[str] = field(default_factory=lambda: ["common"])
    workspace_root: Path | None = None
    output_root: Path | None = None
    protected_locations: list[Path] = field(default_factory=list)
    engines: list[str] = field(default_factory=lambda: ["stirling", "text"])
    workers: int = 3
    engine_settings: dict[str, dict] = field(default_factory=dict)


@dataclass
class AppConfig:
    path: Path
    redaction: RedactionConfig

    @classmethod
    def load(cls, path: Path | None = None) -> AppConfig:
        path = Path(path) if path else default_path()
        data = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        r = data.get("redaction", {})

        def paths(key):
            return [Path(p) for p in r.get(key, []) if p]

        def opt(key):
            return Path(r[key]) if r.get(key) else None

        return cls(
            path=path,
            redaction=RedactionConfig(
                global_term_files=paths("global_term_files"),
                global_alias_files=paths("global_alias_files"),
                pattern_packs=list(r.get("pattern_packs", ["common"])),
                workspace_root=opt("workspace_root"),
                output_root=opt("output_root"),
                protected_locations=paths("protected_locations"),
                engines=list(r.get("engines", ["stirling", "text"])),
                workers=int(r.get("workers", 3)),
                engine_settings=dict(data.get("engines", {})),
            ),
        )

    @staticmethod
    def write_template(path: Path | None = None) -> Path:
        path = Path(path) if path else default_path()
        if path.exists():
            raise FileExistsError("configuration already exists")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(TEMPLATE, encoding="utf-8")
        return path
