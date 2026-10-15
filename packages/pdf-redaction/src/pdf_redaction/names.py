"""Redact file and folder names, one path component at a time.

Rules, in order, for each component (the extension of the last component is kept):
1. aliases: real value -> alias. They go first: the later rules never see (or override) them;
2. terms -> placeholder;
3. names only: any alphanumeric token holding 6 or more digits -> placeholder, unless the token is
   a valid date ``YYYYMMDD`` (``YYYY-MM`` and ``YYYY-MM-DD`` never reach 6 digits in one token);
4. built-in PII patterns -> placeholder;
5. clean-up: invalid Windows characters removed, separators collapsed, reserved names avoided.

Matching runs on two "views" of the component: one where ``_`` and ``-`` count as spaces and one
where ``.``, ``,`` and ``+`` do too, so ``Jane_Example``, ``Example-Jane``, ``Jane.Example`` and
``Example, Jane`` match the term ``Jane Example`` (the first view keeps terms holding dots working).
With ``term_regex(bounded=False)`` ``JaneExample`` and ``ContractJaneExample`` match as well.
Collisions inside the same folder get ``_2``, ``_3``... (``SafePathMapper``).
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import PurePath, PurePosixPath

from pdf_redaction.rules.context import Matcher, RedactionContext
from pdf_redaction.rules.patterns import Strength
from pdf_redaction.rules.terms import normalize

NAME_PLACEHOLDER = "REDACTED"
_SEPARATORS = " ._-,+"
_TOKEN = re.compile(r"[A-Za-z0-9]+")
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
# one character per character, so spans in a view are spans in the component
_VIEWS = (str.maketrans("_-", "  "), str.maketrans("_-.,+", "     "))
# private-use characters standing for an alias while the later rules run: not alphanumeric, not \w
_SENTINEL = 0xE000


def _views(component: str) -> list[str]:
    return list(dict.fromkeys(component.translate(t) for t in _VIEWS))


def _is_date_token(token: str) -> bool:
    if not (len(token) == 8 and token.isdigit()):
        return False
    try:
        date(int(token[:4]), int(token[4:6]), int(token[6:]))
    except ValueError:
        return False
    return 1900 <= int(token[:4]) <= 2100


def long_digit_tokens(component: str) -> list[re.Match]:
    return [
        m
        for m in _TOKEN.finditer(component)
        if sum(c.isdigit() for c in m.group(0)) >= 6 and not _is_date_token(m.group(0))
    ]


def _replace_spans(text: str, spans: list[tuple[int, int, str]]) -> str:
    out, last = [], 0
    for start, end, repl in sorted(spans, key=lambda s: (s[0], -s[1])):  # same start: longest first
        if start < last:  # overlapping hit already covered
            continue
        out.append(text[last:start])
        out.append(repl)
        last = end
    out.append(text[last:])
    return "".join(out)


def _clean(name: str, placeholder: str) -> str:
    name = _INVALID.sub("", name)
    name = re.sub(r"([_\- .])\1+", r"\1", name)
    name = re.sub(r"\s{2,}", " ", name).strip(" ._-")
    if not name:
        return placeholder
    if name.split(".")[0].upper() in _RESERVED:
        name = "_" + name
    return name


class NameRedactor:
    def __init__(self, ctx: RedactionContext, placeholder: str = NAME_PLACEHOLDER):
        self.placeholder = placeholder
        # bounded=False: codes glued to text, joined names and CamelCase boundaries (term_regex)
        self.matchers: list[Matcher] = ctx.matchers(bounded=False)

    def _hits(self, stem: str, kinds: tuple[str, ...]) -> list[tuple[int, int, str, Matcher]]:
        hits = {}
        for view in _views(normalize(stem)):
            for m in self.matchers:
                if m.kind not in kinds:
                    continue
                repl = m.replacement if m.kind == "alias" else self.placeholder
                for x in m.regex.finditer(view):
                    start, end = x.start(), x.end()
                    # keep the separators around a hit ("123456789-Name" -> "REDACTED-Name")
                    while start < end and view[start] in _SEPARATORS:
                        start += 1
                    while end > start and view[end - 1] in _SEPARATORS:
                        end -= 1
                    if start < end:
                        hits.setdefault((start, end, m.label), (start, end, repl, m))
        return list(hits.values())

    def redact_component(self, component: str, *, keep_suffix: bool) -> str:
        component = normalize(component)
        suffix = ""
        stem = component
        if keep_suffix:
            p = PurePosixPath(component)
            if p.suffix and len(p.suffix) <= 6 and p.suffix[1:].isalnum():
                suffix, stem = p.suffix, component[: -len(p.suffix)]
        # 1. aliases, held by a sentinel so the next rules cannot touch them, 2. terms,
        # 3. tokens with many digits (whole token), 4. PII patterns
        alias_hits = self._hits(stem, ("alias",))
        sentinel = {a: chr(_SENTINEL + i) for i, a in enumerate(dict.fromkeys(r for _, _, r, _ in alias_hits))}
        stem = _replace_spans(stem, [(s, e, sentinel[r]) for s, e, r, _ in alias_hits])
        stem = _replace_spans(stem, [(s, e, r) for s, e, r, _ in self._hits(stem, ("term",))])
        stem = _replace_spans(stem, [(m.start(), m.end(), self.placeholder) for m in long_digit_tokens(stem)])
        stem = _replace_spans(stem, [(s, e, r) for s, e, r, _ in self._hits(stem, ("pattern",))])
        for alias, char in sentinel.items():
            stem = stem.replace(char, alias)
        return _clean(stem, self.placeholder) + suffix

    def findings(self, component: str) -> list[tuple[str, Strength]]:
        """(label, strength) of every rule still matching ``component``: used by verification."""
        hits = self._hits(normalize(component), ("alias", "term", "pattern"))
        out = list(dict.fromkeys((m.label, m.strength) for _, _, _, m in hits))
        if long_digit_tokens(normalize(component)):
            out.append(("LONG_DIGIT_CODE_IN_NAME", Strength.WEAK))
        return out


class SafePathMapper:
    """Deterministic original -> redacted relative path mapping with collision handling."""

    def __init__(self, ctx: RedactionContext, placeholder: str = NAME_PLACEHOLDER):
        self.redactor = NameRedactor(ctx, placeholder)
        self._dirs: dict[tuple[str, ...], tuple[str, ...]] = {(): ()}
        self._files: dict[tuple[str, ...], PurePosixPath] = {}
        self._used: dict[tuple[str, ...], set[str]] = {}

    def _unique(self, parent: tuple[str, ...], name: str) -> str:
        used = self._used.setdefault(parent, set())
        candidate, n = name, 1
        stem, dot, ext = name.rpartition(".") if "." in name else (name, "", "")
        while candidate.lower() in used:
            n += 1
            candidate = f"{stem}_{n}{dot}{ext}" if dot else f"{name}_{n}"
        used.add(candidate.lower())
        return candidate

    def _map_dir(self, parts: tuple[str, ...]) -> tuple[str, ...]:
        if parts in self._dirs:
            return self._dirs[parts]
        parent = self._map_dir(parts[:-1])
        name = self._unique(parent, self.redactor.redact_component(parts[-1], keep_suffix=False))
        self._dirs[parts] = parent + (name,)
        return self._dirs[parts]

    def map(self, rel: PurePath) -> PurePosixPath:
        parts = tuple(PurePosixPath(rel.as_posix()).parts)
        if parts not in self._files:
            parent = self._map_dir(parts[:-1])
            name = self._unique(parent, self.redactor.redact_component(parts[-1], keep_suffix=True))
            self._files[parts] = PurePosixPath(*parent, name)
        return self._files[parts]
