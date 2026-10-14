"""A redaction session: a private workspace bound to one read-only source folder.

Workspace layout::

    <workspace>/
      session.json      alias, source folder, creation time
      manifest.json     relative path, size and SHA-256 of every copied original
      originals/        byte-for-byte copy of the source (the ``.redaction`` folder excluded)
      redacted/         engine output, with redacted names
      ledger.csv        what was processed, with which context and engine
      review.json       redacted paths a human has reviewed, with the SHA-256 of what was seen
      logs/

The workspace contains unredacted data: it must live in a private location, never inside a
folder that is shared, synced or readable by other tools (see ``protected`` locations).
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pdf_redaction.guards import GuardError, ensure_disjoint, ensure_not_within
from pdf_redaction.rules.context import CONTEXT_DIRNAME

SESSION_FILE = "session.json"
MANIFEST_FILE = "manifest.json"
ALIAS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def iter_source_files(source: Path):
    for p in sorted(Path(source).rglob("*")):
        rel = p.relative_to(source)
        if rel.parts and rel.parts[0] == CONTEXT_DIRNAME:
            continue
        if p.is_file():
            yield rel


@dataclass
class SyncResult:
    copied: int = 0
    unchanged: int = 0
    removed: int = 0


@dataclass
class Session:
    workspace: Path
    alias: str
    source: Path
    created: str

    @property
    def originals_dir(self) -> Path:
        return self.workspace / "originals"

    @property
    def redacted_dir(self) -> Path:
        return self.workspace / "redacted"

    @property
    def ledger_path(self) -> Path:
        return self.workspace / "ledger.csv"

    @property
    def review_path(self) -> Path:
        return self.workspace / "review.json"

    @property
    def logs_dir(self) -> Path:
        return self.workspace / "logs"

    @staticmethod
    def validate_alias(alias: str) -> None:
        if not ALIAS_RE.match(alias):
            raise GuardError("alias: use 1-64 letters, digits, '.', '_' or '-' (it becomes a public folder name)")

    @classmethod
    def create(cls, source: Path, workspace: Path, alias: str, protected: list[Path] = ()) -> Session:
        source, workspace = Path(source).resolve(), Path(workspace).resolve()
        cls.validate_alias(alias)
        if not source.is_dir():
            raise GuardError("source folder does not exist")
        ensure_disjoint(source, workspace, "source", "workspace")
        ensure_not_within(workspace, list(protected), "workspace")
        if (workspace / SESSION_FILE).exists():
            raise GuardError("a session already exists in this workspace: open it instead")
        workspace.mkdir(parents=True, exist_ok=True)
        session = cls(workspace, alias, source, datetime.now(UTC).isoformat(timespec="seconds"))
        (workspace / SESSION_FILE).write_text(
            json.dumps({"schema": 1, "alias": alias, "source": str(source), "created": session.created}, indent=2),
            encoding="utf-8",
        )
        for d in (session.originals_dir, session.redacted_dir, session.logs_dir):
            d.mkdir(exist_ok=True)
        session.sync_originals()
        return session

    @classmethod
    def open(cls, workspace: Path) -> Session:
        workspace = Path(workspace).resolve()
        try:
            data = json.loads((workspace / SESSION_FILE).read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise GuardError("not a session workspace (session.json missing)") from None
        return cls(workspace, data["alias"], Path(data["source"]), data["created"])

    def sync_originals(self) -> SyncResult:
        """Mirror the source into ``originals/``. The source is only read."""
        result = SyncResult()
        manifest = {}
        seen = set()
        for rel in iter_source_files(self.source):
            src, dst = self.source / rel, self.originals_dir / rel
            seen.add(rel.as_posix())
            st = src.stat()
            if dst.exists() and dst.stat().st_size == st.st_size and int(dst.stat().st_mtime) == int(st.st_mtime):
                result.unchanged += 1
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                result.copied += 1
            manifest[rel.as_posix()] = {"size": st.st_size, "sha256": sha256_file(dst)}
        for p in sorted(self.originals_dir.rglob("*"), reverse=True):
            rel = p.relative_to(self.originals_dir).as_posix()
            if p.is_file() and rel not in seen:
                p.unlink()
                result.removed += 1
            elif p.is_dir() and not any(p.iterdir()):
                p.rmdir()
        (self.workspace / MANIFEST_FILE).write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        return result

    def manifest(self) -> dict[str, dict]:
        path = self.workspace / MANIFEST_FILE
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def _review_marks(self) -> dict[str, str]:
        if not self.review_path.exists():
            return {}
        marks = json.loads(self.review_path.read_text(encoding="utf-8"))
        return marks if isinstance(marks, dict) else {}  # older format without hashes: review again

    def reviewed(self) -> set[str]:
        """Paths marked as reviewed whose redacted file is still the one that was looked at."""
        out = set()
        for rel, digest in self._review_marks().items():
            path = self.redacted_dir / rel
            if path.is_file() and sha256_file(path) == digest:
                out.add(rel)
        return out

    def set_reviewed(self, rel_paths: list[str], value: bool = True) -> None:
        marks = self._review_marks()
        for rel in rel_paths:
            if value:
                marks[rel] = sha256_file(self.redacted_dir / rel)
            else:
                marks.pop(rel, None)
        self.review_path.write_text(json.dumps(dict(sorted(marks.items())), indent=1), encoding="utf-8")
