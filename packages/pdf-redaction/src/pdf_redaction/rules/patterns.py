"""Built-in PII patterns, grouped in packs (``common`` plus one pack per country).

Every regex must be valid both in Python ``re`` and in Java ``java.util.regex`` because the same
pattern is sent to Stirling-PDF. Keep to lookarounds, classes and quantifiers; no named groups,
no possessive quantifiers, no ``(?P...)``.

Strength:
- STRONG: a hit makes verification FAIL (almost never a false positive).
- WEAK: a hit makes verification WARN (may be an amount, a date or a product code).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class Strength(StrEnum):
    STRONG = "strong"
    WEAK = "weak"


@dataclass(frozen=True)
class PiiPattern:
    name: str
    regex: re.Pattern
    strength: Strength
    pack: str


def _p(name: str, pattern: str, strength: Strength, pack: str, flags: int = 0) -> PiiPattern:
    return PiiPattern(name, re.compile(pattern, flags), strength, pack)


_S, _W = Strength.STRONG, Strength.WEAK

_PACKS: dict[str, list[PiiPattern]] = {
    "common": [
        _p("EMAIL", r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", _S, "common"),
        _p("IBAN", r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}(?:\s?[A-Z0-9]{1,3})?\b", _S, "common"),
        _p("LONG_NUMBER", r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)", _W, "common"),
    ],
    "it": [
        _p(
            "TAX_CODE_IT",
            r"\b[A-Z]{6}[0-9LMNPQRSTUV]{2}[ABCDEHLMPRST][0-9LMNPQRSTUV]{2}[A-Z][0-9LMNPQRSTUV]{3}[A-Z]\b",
            _S,
            "it",
            re.I,
        ),
        _p("IBAN_IT", r"\bIT\s?\d{2}\s?[A-Z]\s?(?:\d\s?){10}(?:[A-Z0-9]\s?){11}[A-Z0-9]\b", _S, "it", re.I),
        _p("MOBILE_PHONE_IT", r"(?<!\d)(?:(?:\+39|0039)[\s.]?)?3\d{2}[\s.-]?\d{6,7}(?!\d)", _S, "it"),
        _p("LANDLINE_PHONE_IT", r"(?<!\d)(?:\+39|0039)?\s?0\d{1,3}[\s/.-]?\d{5,8}(?!\d)", _W, "it"),
        _p("VAT_NUMBER_IT", r"(?<!\d)\d{11}(?!\d)", _W, "it"),
    ],
}


def available_packs() -> list[str]:
    return list(_PACKS)


def get_patterns(packs: list[str] | tuple[str, ...]) -> list[PiiPattern]:
    unknown = [p for p in packs if p not in _PACKS]
    if unknown:
        raise ValueError(f"unknown pattern pack(s): {', '.join(unknown)}; available: {', '.join(_PACKS)}")
    out: list[PiiPattern] = []
    for pack in packs:
        out.extend(_PACKS[pack])
    return out
