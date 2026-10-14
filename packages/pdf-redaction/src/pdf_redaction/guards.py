"""Path guards that keep unredacted data where it belongs."""

from __future__ import annotations

import os
from pathlib import Path


class GuardError(ValueError):
    """A path violates a privacy guard. Messages name the rule, not the path."""


def _real(path: Path) -> Path:
    return Path(os.path.realpath(Path(path).expanduser()))


def is_within(path: Path, parent: Path) -> bool:
    p, q = _real(path), _real(parent)
    return p == q or q in p.parents


def ensure_not_within(path: Path, forbidden: list[Path], what: str) -> None:
    for i, f in enumerate(forbidden, 1):
        if is_within(path, f):
            raise GuardError(f"{what} is inside protected location #{i}: choose another folder")


def ensure_disjoint(a: Path, b: Path, what_a: str, what_b: str) -> None:
    if is_within(a, b) or is_within(b, a):
        raise GuardError(f"{what_a} and {what_b} must not contain each other")
