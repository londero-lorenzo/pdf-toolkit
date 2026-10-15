"""Run a session: redact names and contents, verify, record. Incremental and parallel.

Redacted files edited by hand after a run become the base of later runs (see ``manual``).
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath

from pdf_redaction.engines.base import Engine, EngineError, engine_for
from pdf_redaction.ledger import Ledger, LedgerEntry
from pdf_redaction.manual import DROP_NO_REBASE, DROP_ORIGINAL_CHANGED, DROP_RULES_REMOVED, ManualStore, Rulesets
from pdf_redaction.names import SafePathMapper
from pdf_redaction.rules.context import RedactionContext
from pdf_redaction.session import Session, sha256_file
from pdf_redaction.verify import FileVerdict, verify_file

BASE_MANUAL = "manual"


@dataclass
class ItemResult:
    original: str  # private: never print
    redacted: str  # redacted relative path
    outcome: str  # "redacted" | "unchanged" | "unsupported" | "error"
    verdict: FileVerdict | None = None
    error: str = ""
    remote_calls: int = 0
    manual: bool = False  # the output is built on top of a manual edit
    manual_dropped: str = ""  # why a manual edit could not be kept (a fixed label, never a name)


@dataclass
class RunReport:
    items: list[ItemResult]
    context_changed: int = 0  # files redone because the rules changed
    manual_found: int = 0  # files edited by hand since the last run

    @property
    def remote_calls(self) -> int:
        return sum(i.remote_calls for i in self.items)

    @property
    def manual_rebuilt(self) -> int:
        return sum(1 for i in self.items if i.manual and i.outcome == "redacted")

    @property
    def manual_dropped(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for i in self.items:
            if i.manual_dropped:
                out[i.manual_dropped] = out.get(i.manual_dropped, 0) + 1
        return out

    def count(self, outcome: str) -> int:
        return sum(1 for i in self.items if i.outcome == outcome)


def plan_names(session: Session, ctx: RedactionContext) -> list[tuple[str, str]]:
    """(original, redacted) relative paths, deterministic for a given context."""
    mapper = SafePathMapper(ctx)
    originals = sorted(session.manifest())
    return [(o, mapper.map(PurePosixPath(o)).as_posix()) for o in originals]


def _engine_rules(
    engines: dict[str, Engine], ctx: RedactionContext
) -> tuple[dict[str, frozenset[str] | None], dict[str, str]]:
    """Rule digests per engine name (None: the engine cannot tell) and errors while computing them."""
    rules: dict[str, frozenset[str] | None] = {}
    errors: dict[str, str] = {}
    for engine in engines.values():
        hook = getattr(engine, "rule_digests", None)
        if hook is None:
            rules[engine.name] = None
            continue
        try:
            rules[engine.name] = frozenset(hook(ctx))
        except Exception as exc:  # e.g. a term the engine refuses: the message might quote it
            errors[engine.name] = f"{type(exc).__name__} while preparing the rules of engine {engine.name}"
    return rules, errors


def capture_manual_edits(session: Session, ledger: Ledger, manual: ManualStore, rulesets: Rulesets) -> set[str]:
    """Copy outputs edited after the last run into ``manual/``; return their original paths."""
    found = set()
    for original, e in ledger.entries.items():
        if ledger.edited_after_run(original, session.redacted_dir):
            applied = rulesets.get(e.context_fingerprint, e.engine.split("/", 1)[0])
            manual.capture(original, session.redacted_dir / e.redacted, e.original_sha256, applied)
            found.add(original)
    return found


def run_session(
    session: Session,
    ctx: RedactionContext,
    engines: dict[str, Engine],
    *,
    workers: int = 3,
    force: bool = False,
    progress: Callable[[int, int], None] | None = None,
) -> RunReport:
    manifest = session.manifest()
    ledger = Ledger(session.ledger_path)
    ledger.drop_missing(set(manifest))
    manual = ManualStore(session)
    rulesets = Rulesets(session)
    # before any output is replaced or removed, or the edit would be lost
    edited = capture_manual_edits(session, ledger, manual, rulesets)
    manual.drop_missing(set(manifest))
    fingerprint = ctx.fingerprint()
    engine_rules, rule_errors = _engine_rules(engines, ctx)
    plan = plan_names(session, ctx)
    expected = {r for _, r in plan}
    changed = sum(
        1 for o, _ in plan if o in ledger.entries and ledger.entries[o].context_fingerprint not in ("", fingerprint)
    )

    # outputs of files that disappeared or got a different name
    for p in sorted(session.redacted_dir.rglob("*"), reverse=True):
        rel = p.relative_to(session.redacted_dir).as_posix()
        if p.is_file() and rel not in expected:
            p.unlink()
        elif p.is_dir() and not any(p.iterdir()):
            p.rmdir()

    done = 0
    total = len(plan)

    def work(item: tuple[str, str]) -> ItemResult:
        original, redacted = item
        src = session.originals_dir / original
        dst = session.redacted_dir / redacted
        engine = engine_for(src, engines)
        if engine is None:
            return ItemResult(original, redacted, "unsupported")
        engine_id = f"{engine.name}/{engine.version}"
        sha = manifest[original]["sha256"]
        if (
            not force
            and original not in edited  # a fresh edit is always sanitized and verified by a run
            and ledger.is_current(original, sha, fingerprint, engine_id, session.redacted_dir)
        ):
            on_manual = ledger.entries[original].base == BASE_MANUAL
            return ItemResult(
                original, redacted, "unchanged", verify_file(dst, PurePosixPath(redacted), ctx), manual=on_manual
            )
        base, dropped = src, ""
        if (edit := manual.active(original)) is not None:
            if engine.name in rule_errors:
                return ItemResult(original, redacted, "error", error=rule_errors[engine.name])
            current = engine_rules.get(engine.name)
            if edit.original_sha256 != sha:
                dropped = DROP_ORIGINAL_CHANGED
            elif current is None:
                dropped = DROP_NO_REBASE
            elif edit.rules is None or not set(edit.rules) <= current:
                dropped = DROP_RULES_REMOVED
            else:
                base = manual.file_for(original)
        tmp = dst.with_name(dst.name + ".part")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        try:
            result = engine.redact(base, tmp, ctx)
            tmp.replace(dst)
        except EngineError as exc:
            tmp.unlink(missing_ok=True)
            return ItemResult(original, redacted, "error", error=str(exc))
        except Exception as exc:  # never surface messages that might quote content
            tmp.unlink(missing_ok=True)
            return ItemResult(original, redacted, "error", error=f"{type(exc).__name__} in engine {engine.name}")
        if dropped:  # only once the file was really redone: a failed run keeps the edit in use
            manual.mark_stale(original, dropped)
        on_manual = base != src
        verdict = verify_file(dst, PurePosixPath(redacted), ctx)
        ledger.record(
            LedgerEntry(
                original,
                redacted,
                sha,
                fingerprint,
                engine_id,
                "done",
                datetime.now(UTC).isoformat(timespec="seconds"),
                sha256_file(dst),
                BASE_MANUAL if on_manual else "",
            )
        )
        return ItemResult(
            original,
            redacted,
            "redacted",
            verdict,
            remote_calls=result.remote_calls,
            manual=on_manual,
            manual_dropped=dropped,
        )

    items: list[ItemResult] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for res in pool.map(work, plan):
            items.append(res)
            done += 1
            if progress:
                progress(done, total)
    ledger.save()
    manual.save()
    for name, rules in engine_rules.items():
        if rules is not None:
            rulesets.set(fingerprint, name, rules)
    rulesets.save({e.context_fingerprint for e in ledger.entries.values()})
    return RunReport(items, context_changed=changed, manual_found=len(edited))


def discard_manual_edits(session: Session, redacted: list[str] | None = None) -> int:
    """Forget the manual edits of the given redacted paths (all if None): the next run redoes those
    files from the originals. Returns how many edits were discarded."""
    manual = ManualStore(session)
    ledger = Ledger(session.ledger_path)
    if redacted is None:
        edited = {o for o in ledger.entries if ledger.edited_after_run(o, session.redacted_dir)}
        originals = set(manual.entries) | edited
    else:
        wanted = set(redacted)
        originals = {o for o, e in ledger.entries.items() if e.redacted in wanted}
    count = 0
    for original in sorted(originals):
        e = ledger.entries.get(original)
        edited = ledger.edited_after_run(original, session.redacted_dir)
        if manual.discard(original) or edited:
            count += 1
        # the output is the edit itself or was built on it: the next run must redo it
        if e and (edited or e.base == BASE_MANUAL):
            e.result = "stale"
            e.output_sha256 = ""
            e.base = ""
    ledger.save()
    manual.save()
    return count


def verify_session(session: Session, ctx: RedactionContext) -> list[FileVerdict]:
    """Verify every file currently in ``redacted/``."""
    root = session.redacted_dir
    return [verify_file(p, p.relative_to(root), ctx) for p in sorted(root.rglob("*")) if p.is_file()]
