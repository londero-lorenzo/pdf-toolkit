"""The redaction context of a source folder.

A context merges:
- the user's global term and alias files (paths come from the app configuration);
- the folder's own files in ``<source>/.redaction/``:
    terms.txt      one term per line
    aliases.csv    real,alias   (the real value is replaced by the alias instead of the placeholder)
    settings.toml  pattern_packs = ["common", "it"]   drop_columns = ["Holder"]
- the built-in PII pattern packs.

The fingerprint changes whenever any rule changes, so already processed files are redone.
"""

from __future__ import annotations

import hashlib
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from pdf_redaction.rules.patterns import PiiPattern, Strength, get_patterns
from pdf_redaction.rules.terms import Alias, Term, load_aliases, load_terms, term_regex

CONTEXT_DIRNAME = ".redaction"
TERMS_FILENAME = "terms.txt"
ALIASES_FILENAME = "aliases.csv"
SETTINGS_FILENAME = "settings.toml"
DEFAULT_PLACEHOLDER = "[REDACTED]"
DEFAULT_PACKS = ("common",)


@dataclass(frozen=True)
class Matcher:
    label: str  # printable: never contains the matched value
    regex: re.Pattern
    strength: Strength
    replacement: str
    kind: str  # "alias" | "term" | "pattern"


@dataclass(frozen=True)
class FolderSettings:
    pattern_packs: tuple[str, ...] | None = None  # None = use the app default
    drop_columns: tuple[str, ...] = ()

    @classmethod
    def load(cls, path: Path) -> FolderSettings:
        if not path.exists():
            return cls()
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        packs = data.get("pattern_packs")
        return cls(
            pattern_packs=tuple(packs) if packs is not None else None,
            drop_columns=tuple(data.get("drop_columns", ())),
        )

    def save(self, path: Path) -> None:
        def arr(values) -> str:
            return "[" + ", ".join('"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"' for v in values) + "]"

        lines = ["# Redaction settings for this folder"]
        if self.pattern_packs is not None:
            lines.append(f"pattern_packs = {arr(self.pattern_packs)}")
        lines.append(f"drop_columns = {arr(self.drop_columns)}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def context_dir(source: Path) -> Path:
    return Path(source) / CONTEXT_DIRNAME


@dataclass
class RedactionContext:
    terms: list[Term] = field(default_factory=list)
    aliases: list[Alias] = field(default_factory=list)
    patterns: list[PiiPattern] = field(default_factory=list)
    drop_columns: tuple[str, ...] = ()
    placeholder: str = DEFAULT_PLACEHOLDER

    @classmethod
    def load(
        cls,
        source: Path | None,
        *,
        global_term_files: list[Path] = (),
        global_alias_files: list[Path] = (),
        default_packs: tuple[str, ...] | list[str] = DEFAULT_PACKS,
        placeholder: str = DEFAULT_PLACEHOLDER,
    ) -> RedactionContext:
        terms: list[Term] = []
        aliases: list[Alias] = []
        for i, f in enumerate(global_term_files, 1):
            terms += load_terms(Path(f), f"global{i if len(global_term_files) > 1 else ''}")
        for i, f in enumerate(global_alias_files, 1):
            aliases += load_aliases(Path(f), f"global-alias{i if len(global_alias_files) > 1 else ''}")
        settings = FolderSettings()
        if source is not None:
            cdir = context_dir(source)
            terms += load_terms(cdir / TERMS_FILENAME, "folder")
            aliases += load_aliases(cdir / ALIASES_FILENAME, "folder-alias")
            settings = FolderSettings.load(cdir / SETTINGS_FILENAME)
        # same term from two files: keep the first occurrence
        unique, seen = [], set()
        for t in terms:
            if t.value.lower() not in seen:
                seen.add(t.value.lower())
                unique.append(t)
        packs = settings.pattern_packs if settings.pattern_packs is not None else tuple(default_packs)
        return cls(
            terms=unique,
            aliases=aliases,
            patterns=get_patterns(list(packs)),
            drop_columns=settings.drop_columns,
            placeholder=placeholder,
        )

    @property
    def is_empty(self) -> bool:
        return not (self.terms or self.aliases or self.patterns)

    def fingerprint(self) -> str:
        h = hashlib.sha256()
        for t in sorted(t.value.lower() for t in self.terms):
            h.update(b"T" + t.encode() + b"\0")
        for a in sorted((a.real.lower(), a.alias) for a in self.aliases):
            h.update(b"A" + a[0].encode() + b"\0" + a[1].encode() + b"\0")
        for p in self.patterns:
            h.update(b"P" + p.name.encode() + b"\0" + p.regex.pattern.encode() + b"\0")
        for c in self.drop_columns:
            h.update(b"C" + c.lower().encode() + b"\0")
        h.update(b"R" + self.placeholder.encode())
        return h.hexdigest()

    def matchers(self, *, bounded: bool = True) -> list[Matcher]:
        """Ordered matchers: aliases, then terms (longest first), then built-in patterns."""
        out = [
            Matcher(f"alias {a.label}", term_regex(a.real, bounded=bounded), Strength.STRONG, a.alias, "alias")
            for a in sorted(self.aliases, key=lambda a: len(a.real), reverse=True)
        ]
        out += [
            Matcher(f"term {t.label}", term_regex(t.value, bounded=bounded), Strength.STRONG, self.placeholder, "term")
            for t in sorted(self.terms, key=lambda t: len(t.value), reverse=True)
        ]
        out += [Matcher(p.name, p.regex, p.strength, self.placeholder, "pattern") for p in self.patterns]
        return out

    def counts(self) -> dict[str, int]:
        return {"terms": len(self.terms), "aliases": len(self.aliases), "patterns": len(self.patterns)}
