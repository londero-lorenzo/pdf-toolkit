"""Turn a RedactionContext into regexes for Stirling-PDF (one pattern per line).

Stirling-PDF 3.1 matches with its own engine, whose dialect is narrower than Java's. Tested against
the real server: a rule containing a ``\\uXXXX`` escape or the ``u`` inline flag is **dropped
silently** (the other rules still apply), while ``(?i:...)``, look-arounds, ``\\x{hh}`` escapes and
Latin-1 ranges work, and matching is case-insensitive anyway. Every pattern sent is therefore
rewritten to that subset and checked; verification still catches anything the engine leaves behind.
"""

from __future__ import annotations

import re

from pdf_redaction.rules.context import RedactionContext
from pdf_redaction.rules.terms import term_regex

# an unescaped \uXXXX (preceded by an even number of backslashes)
_U_ESCAPE = re.compile(r"(?<!\\)((?:\\\\)*)\\u([0-9A-Fa-f]{4})")
# an unescaped \x{...}
_X_BRACE = re.compile(r"(?<!\\)((?:\\\\)*)\\x\{([0-9a-fA-F]{1,4})\}")
# an inline flag group or setting containing "u": (?u) (?iu: (?ui) ...
_U_FLAG = re.compile(r"\(\?[a-zA-Z]*u[a-zA-Z]*[:)]")


def unsupported_by_stirling(pattern: str) -> bool:
    """True if Stirling-PDF would silently ignore this pattern."""
    return bool(_U_ESCAPE.search(pattern) or _U_FLAG.search(pattern))


def to_stirling_dialect(pattern: str) -> str:
    """Rewrite ``\\uXXXX`` as ``\\x{XXXX}``; raise ValueError if a construct Stirling drops remains."""
    out = _U_ESCAPE.sub(lambda m: m.group(1) + "\\x{" + f"{int(m.group(2), 16):x}" + "}", pattern)
    if unsupported_by_stirling(out):
        raise ValueError("pattern uses a construct Stirling-PDF ignores (\\u escape or u flag)")
    return out


def to_python(pattern: str) -> str:
    """Inverse of the ``\\x{...}`` rewrite, to compile a Stirling pattern with Python's ``re``."""
    return _X_BRACE.sub(lambda m: m.group(1) + f"\\u{int(m.group(2), 16):04x}", pattern)


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
        out.append(to_stirling_dialect("(?i:" + rx.pattern + ")"))
    for p in ctx.patterns:
        out.append(to_stirling_dialect(f"(?i:{p.regex.pattern})" if p.regex.flags & re.I else p.regex.pattern))
    return list(dict.fromkeys(out))
