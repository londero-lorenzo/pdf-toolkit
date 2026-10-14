"""Per-session processing ledger (CSV in the private workspace)."""

from __future__ import annotations

import csv
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass
class LedgerEntry:
    original: str  # original relative path (private: stays in the workspace)
    redacted: str  # redacted relative path
    original_sha256: str
    context_fingerprint: str
    engine: str  # "<name>/<version>"
    result: str  # "done" | "error" | "unsupported"
    finished_at: str


class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.entries: dict[str, LedgerEntry] = {}
        if self.path.exists():
            with open(self.path, encoding="utf-8", newline="") as fh:
                for row in csv.DictReader(fh):
                    self.entries[row["original"]] = LedgerEntry(
                        **{f.name: row.get(f.name, "") for f in fields(LedgerEntry)}
                    )

    def is_current(self, original: str, sha: str, fingerprint: str, engine: str, redacted_root: Path) -> bool:
        e = self.entries.get(original)
        return bool(
            e
            and e.result == "done"
            and e.original_sha256 == sha
            and e.context_fingerprint == fingerprint
            and e.engine == engine
            and (redacted_root / e.redacted).exists()
        )

    def record(self, entry: LedgerEntry) -> None:
        self.entries[entry.original] = entry

    def drop_missing(self, originals: set[str]) -> None:
        for key in [k for k in self.entries if k not in originals]:
            del self.entries[key]

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=[f.name for f in fields(LedgerEntry)])
            writer.writeheader()
            for key in sorted(self.entries):
                writer.writerow(asdict(self.entries[key]))
        os.replace(tmp, self.path)
