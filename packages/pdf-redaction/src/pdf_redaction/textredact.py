"""Apply a RedactionContext to plain text."""

from __future__ import annotations

from collections import Counter

from pdf_redaction.rules.context import RedactionContext
from pdf_redaction.rules.terms import normalize


class TextRedactor:
    def __init__(self, ctx: RedactionContext):
        self.matchers = ctx.matchers()
        self.counts: Counter[str] = Counter()

    def apply(self, text: str) -> str:
        text = normalize(text)
        for m in self.matchers:
            text, n = m.regex.subn(m.replacement, text)
            if n:
                self.counts[m.label] += n
        return text
