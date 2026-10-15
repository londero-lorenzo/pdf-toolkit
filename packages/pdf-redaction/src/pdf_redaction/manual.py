"""Manual edits made to redacted files after a run (for example boxes drawn in Stirling-PDF's viewer).

A redacted file whose SHA-256 no longer matches what the last run wrote was edited by a person.
The next run captures it into ``<workspace>/manual/<original path>`` and uses it as the *base* of
that file from then on: the engine applies the current rules on top of it, so the manual work is
kept when terms or aliases are added.

The base is dropped, and the file redone from the original, when:

- the original changed (the edit belongs to a document that no longer exists);
- the engine cannot tell which rules it applies (no ``rule_digests``, e.g. the text engine);
- a rule applied before the edit is no longer in the context. Keeping the base would never leak
  anything (it only keeps more redacted), but the rule was removed on purpose.

A dropped edit stays in ``manual/``, marked stale, until a new edit replaces it or it is discarded.
The workspace is private: rule digests and original paths stored here are never printed.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from pdf_redaction.session import Session, sha256_file

DROP_ORIGINAL_CHANGED = "original changed"
DROP_NO_REBASE = "engine cannot rebuild on top of it"
DROP_RULES_REMOVED = "rules removed"


def rule_digests(rules: Iterable[str]) -> frozenset[str]:
    """Digests of the effective rules an engine applies (what engines return from ``rule_digests``)."""
    return frozenset(hashlib.sha256(r.encode("utf-8")).hexdigest() for r in rules)


def _write_json(path: Path, data) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


@dataclass
class ManualEdit:
    original_sha256: str  # the original the edited file was redacted from
    manual_sha256: str
    rules: list[str] | None  # digests of the rules already applied before the edit; None if unknown
    captured_at: str
    stale: str = ""  # why the edit is no longer used ("" while it is the base of the file)


class ManualStore:
    """``manual.json`` plus the captured files in ``manual/``, keyed by original relative path."""

    def __init__(self, session: Session):
        self.session = session
        self.entries: dict[str, ManualEdit] = {}
        if session.manual_path.exists():
            data = json.loads(session.manual_path.read_text(encoding="utf-8"))
            for original, row in data.items():
                self.entries[original] = ManualEdit(**row)

    def file_for(self, original: str) -> Path:
        return self.session.manual_dir / original

    def active(self, original: str) -> ManualEdit | None:
        edit = self.entries.get(original)
        return edit if edit and not edit.stale and self.file_for(original).is_file() else None

    def capture(self, original: str, edited: Path, original_sha256: str, rules: frozenset[str] | None) -> None:
        target = self.file_for(original)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(edited, target)
        self.entries[original] = ManualEdit(
            original_sha256,
            sha256_file(target),
            sorted(rules) if rules is not None else None,
            datetime.now(UTC).isoformat(timespec="seconds"),
        )

    def mark_stale(self, original: str, reason: str) -> None:
        if original in self.entries:
            self.entries[original].stale = reason

    def discard(self, original: str) -> bool:
        """Forget the edit of one file and delete its copy. True if there was one."""
        found = self.entries.pop(original, None) is not None
        path = self.file_for(original)
        if path.is_file():
            path.unlink()
            found = True
        return found

    def drop_missing(self, originals: set[str]) -> None:
        for original in [k for k in self.entries if k not in originals]:
            self.discard(original)

    def save(self) -> None:
        if self.entries or self.session.manual_path.exists():
            _write_json(self.session.manual_path, {k: asdict(v) for k, v in sorted(self.entries.items())})
        root = self.session.manual_dir
        if root.is_dir():
            for p in sorted(root.rglob("*"), reverse=True):
                if p.is_dir() and not any(p.iterdir()):
                    p.rmdir()


class Rulesets:
    """``rulesets.json``: ``{context fingerprint: {engine name: [rule digests]}}``.

    It tells which rules a redacted file had already been through, given the fingerprint recorded
    in the ledger, so that a later manual edit can be rebased only on a superset of them.
    """

    def __init__(self, session: Session):
        self.path = session.rulesets_path
        self.data: dict[str, dict[str, list[str]]] = {}
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))

    def get(self, fingerprint: str, engine: str) -> frozenset[str] | None:
        rules = self.data.get(fingerprint, {}).get(engine)
        return frozenset(rules) if rules is not None else None

    def set(self, fingerprint: str, engine: str, rules: frozenset[str]) -> None:
        self.data.setdefault(fingerprint, {})[engine] = sorted(rules)

    def save(self, keep: set[str]) -> None:
        """Write only the fingerprints still referenced (``keep``)."""
        self.data = {k: v for k, v in self.data.items() if k in keep}
        _write_json(self.path, self.data)
