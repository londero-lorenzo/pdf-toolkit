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


def load_aliases(path: Path, label_prefix: str) -> list[Alias]:
    """CSV with two columns ``real,alias`` (header optional, ``;`` or ``,``)."""
    path = Path(path)
    if not path.exists():
        return []
    text = read_text(path)
    delimiter = ";" if text.count(";") > text.count(",") else ","
    out = []
    for number, row in enumerate(csv.reader(text.splitlines(), delimiter=delimiter), 1):
        if len(row) < 2 or not row[0].strip() or not row[1].strip() or row[0].lstrip().startswith("#"):
            continue
        real, alias = normalize(row[0]).strip(), row[1].strip()
        if number == 1 and real.lower() == "real" and alias.lower() == "alias":
            continue
        out.append(Alias(real, alias, f"{label_prefix}#{number}"))
    return out


def write_terms(path: Path, terms: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "# One term per line. Lines starting with # are comments.\n"
    path.write_text(body + "".join(t.strip() + "\n" for t in terms if t.strip()), encoding="utf-8")


def write_aliases(path: Path, aliases: list[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["real", "alias"])
        writer.writerows([(r.strip(), a.strip()) for r, a in aliases if r.strip() and a.strip()])
