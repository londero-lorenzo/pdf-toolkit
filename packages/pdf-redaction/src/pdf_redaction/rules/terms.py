"""User-supplied terms (one per line) and aliases (real value -> pseudonym).

``term_regex`` builds a tolerant pattern for a term:
- people's names (2-3 words, no digits) also match in any word order ("Surname Name");
- codes (one token, >= 8 alphanumerics, at least one digit) tolerate separators between characters
  ("AB 12-34/56" matches "AB123456");
- whitespace is flexible (spaces, line breaks, non-breaking spaces).

The generated pattern is valid in Python and Java, so the same rule drives Stirling and our checks.
"""

from __future__ import annotations

import csv
import itertools
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

# Letters and digits including Latin-1 accented letters; explicit ranges work the same in Java.
ALNUM = "A-Za-z0-9À-ÖØ-öø-ÿ"
WS = "[\\s\\u00a0]"
CODE_SEPARATORS = "[\\s\\u00a0.\\-/_]"
TERMS_HEADER = "# One term per line. Lines starting with # are comments."
ALIASES_HEADER = "# One alias per line: real value, then alias. Lines starting with # are comments."


@dataclass(frozen=True)
class Term:
    value: str
    label: str  # where it comes from, e.g. "global#3" or "folder#7"; safe to print


@dataclass(frozen=True)
class Alias:
    real: str
    alias: str
    label: str


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def read_text(path: Path) -> str:
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def is_code(term: str) -> bool:
    compact = re.sub(r"[\s.\-/_]", "", term)
    return " " not in term.strip() and len(compact) >= 8 and compact.isalnum() and any(c.isdigit() for c in compact)


def term_regex(term: str, *, bounded: bool = True) -> re.Pattern:
    """Case-insensitive pattern for ``term``.

    ``bounded=False`` drops the alphanumeric boundaries for codes, which is what file names need
    (a code is often glued to a prefix: ``ABC12345678.pdf``).
    """
    t = normalize(term).strip()
    if is_code(t):
        compact = re.sub(r"[\s.\-/_]", "", t)
        body = (CODE_SEPARATORS + "?").join(re.escape(c) for c in compact)
        if not bounded:
            return re.compile(body, re.I)
        return re.compile(f"(?<![{ALNUM}])" + body + f"(?![{ALNUM}])", re.I)
    words = t.split()
    if 2 <= len(words) <= 3 and not any(c.isdigit() for c in t):
        orders = list(itertools.permutations(words))
    else:
        orders = [tuple(words)]
    alternatives = [(WS + "+").join(re.escape(w) for w in order) for order in orders]
    body = "(?:" + "|".join(alternatives) + ")" if len(alternatives) > 1 else alternatives[0]
    pre = f"(?<![{ALNUM}])" if t[:1].isalnum() else ""
    post = f"(?![{ALNUM}])" if t[-1:].isalnum() else ""
    return re.compile(pre + body + post, re.I)


def load_terms(path: Path, label_prefix: str) -> list[Term]:
    """One term per line; ``#`` starts a comment line; duplicates (case-insensitive) dropped."""
    path = Path(path)
    if not path.exists():
        return []
    out, seen = [], set()
    for number, line in enumerate(read_text(path).splitlines(), 1):
        value = normalize(line).strip()
        if value and not value.startswith("#") and value.lower() not in seen:
            seen.add(value.lower())
            out.append(Term(value, f"{label_prefix}#{number}"))
    return out


def _is_note(line: str) -> bool:
    """A blank line or a ``#`` comment: kept in the files, never a rule."""
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


def _is_header(row: list[str]) -> bool:
    return len(row) >= 2 and row[0].strip().lower() == "real" and row[1].strip().lower() == "alias"


def _alias_delimiter(lines: list[str]) -> str:
    data = "\n".join(line for line in lines if not _is_note(line))
    return ";" if data.count(";") > data.count(",") else ","


def _alias_rows(path: Path):
    """Yield ``(line number, raw line, parsed row or None for notes and the header)``."""
    lines = read_text(path).splitlines()
    delimiter = _alias_delimiter(lines)
    first = True
    for number, line in enumerate(lines, 1):
        if _is_note(line):
            yield number, line, None
            continue
        row = next(csv.reader([line], delimiter=delimiter), [])
        header, first = first and _is_header(row), False
        yield number, line, None if header else row


def load_aliases(path: Path, label_prefix: str) -> list[Alias]:
    """CSV with two columns ``real,alias`` (header optional, ``;`` or ``,``; ``#`` comments and blank lines ignored)."""
    path = Path(path)
    if not path.exists():
        return []
    out = []
    for number, _, row in _alias_rows(path):
        if row is None or len(row) < 2 or not row[0].strip() or not row[1].strip() or row[0].lstrip().startswith("#"):
            continue
        out.append(Alias(normalize(row[0]).strip(), row[1].strip(), f"{label_prefix}#{number}"))
    return out


def write_terms(path: Path, terms: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TERMS_HEADER + "\n" + "".join(t.strip() + "\n" for t in terms if t.strip()), encoding="utf-8")


def write_aliases(path: Path, aliases: list[tuple[str, str] | str], *, header: bool = True) -> None:
    """One ``real,alias`` row per alias; ``str`` entries are comment or blank lines, written as they are.

    The first line is the ``ALIASES_HEADER`` comment. ``header=False`` (the editor) writes the entries
    as typed, and the header only when there are none.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        if header or not aliases:
            fh.write(ALIASES_HEADER + writer.dialect.lineterminator)
        for entry in aliases:
            if isinstance(entry, str):
                if not _is_note(entry):
                    raise ValueError("write_aliases: text entries must be comments or blank lines")
                fh.write(entry.rstrip() + writer.dialect.lineterminator)
            elif entry[0].strip() and entry[1].strip():
                writer.writerow((entry[0].strip(), entry[1].strip()))


# Editor round trip: the GUI shows and saves the files as written, comments and blank lines included.


def read_terms_text(path: Path) -> str:
    path = Path(path)
    return "\n".join(read_text(path).splitlines()).rstrip() if path.exists() else ""


def write_terms_text(path: Path, text: str) -> None:
    lines = [line.rstrip() for line in text.splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(line + "\n" for line in lines or [TERMS_HEADER]), encoding="utf-8")


def read_aliases_text(path: Path) -> str:
    """``aliases.csv`` as editor text: ``real ; alias`` per row, comments and blank lines verbatim.

    A legacy ``real,alias`` header row is dropped, so the next save no longer writes it.
    """
    path = Path(path)
    if not path.exists():
        return ""
    out = []
    for _, line, row in _alias_rows(path):
        if row is None:
            if _is_note(line):
                out.append(line.rstrip())
        elif len(row) >= 2 and row[0].strip() and row[1].strip():
            out.append(f"{row[0].strip()} ; {row[1].strip()}")
        else:
            out.append(line.rstrip())  # unusable row: shown as is, so saving asks to fix it
    return "\n".join(out).rstrip()


def parse_aliases_text(text: str) -> list[tuple[str, str] | str]:
    """Editor text to ``write_aliases`` entries; raises ``ValueError`` naming only the line number."""
    entries: list[tuple[str, str] | str] = []
    for number, line in enumerate(text.splitlines(), 1):
        if _is_note(line):
            entries.append(line.rstrip())
            continue
        real, sep, alias = line.partition(";")
        if not sep or not real.strip() or not alias.strip():
            raise ValueError(f"Line {number}: use 'real value ; alias'")
        entries.append((real.strip(), alias.strip()))
    while entries and entries[-1] == "":
        entries.pop()
    return entries
