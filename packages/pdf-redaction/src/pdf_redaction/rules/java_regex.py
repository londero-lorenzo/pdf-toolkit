"""Turn a RedactionContext into regexes for Stirling-PDF (Java syntax, one pattern per line)."""

from __future__ import annotations

import re

from pdf_redaction.rules.context import RedactionContext
from pdf_redaction.rules.terms import term_regex


def to_java_patterns(ctx: RedactionContext) -> list[str]:
    """Aliases' real values, terms and built-in patterns; longest literal rules first, no duplicates.

    Raises ValueError (without the value) if a term would not be matched in full by its own rule.
    """
    values = [a.real for a in ctx.aliases] + [t.value for t in ctx.terms]
    values = sorted(dict.fromkeys(values), key=len, reverse=True)
    out: list[str] = []
    for index, value in enumerate(values, 1):
        rx = term_regex(value)
        match = rx.search(value)
        if not match or match.group(0).lower() != value.strip().lower():
            raise ValueError(f"rule #{index} does not match its own term in full")
        out.append("(?iu:" + rx.pattern + ")")
    for p in ctx.patterns:
        out.append(f"(?i:{p.regex.pattern})" if p.regex.flags & re.I else p.regex.pattern)
    return list(dict.fromkeys(out))
