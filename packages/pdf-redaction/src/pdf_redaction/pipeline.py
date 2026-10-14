"""Run a session: redact names and contents, verify, record. Incremental and parallel."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath

from pdf_redaction.engines.base import Engine, EngineError, engine_for
from pdf_redaction.ledger import Ledger, LedgerEntry
from pdf_redaction.names import SafePathMapper
from pdf_redaction.rules.context import RedactionContext
from pdf_redaction.session import Session
from pdf_redaction.verify import FileVerdict, verify_file


@dataclass
class ItemResult:
    original: str  # private: never print
    redacted: str  # redacted relative path
    outcome: str  # "redacted" | "unchanged" | "unsupported" | "error"
    verdict: FileVerdict | None = None
    error: str = ""
    remote_calls: int = 0


@dataclass
class RunReport:
    items: list[ItemResult]
    context_changed: int = 0  # files redone because the rules changed

    @property
    def remote_calls(self) -> int:
        return sum(i.remote_calls for i in self.items)

    def count(self, outcome: str) -> int:
        return sum(1 for i in self.items if i.outcome == outcome)


def plan_names(session: Session, ctx: RedactionContext) -> list[tuple[str, str]]:
    """(original, redacted) relative paths, deterministic for a given context."""
    mapper = SafePathMapper(ctx)
    originals = sorted(session.manifest())
    return [(o, mapper.map(PurePosixPath(o)).as_posix()) for o in originals]


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
    fingerprint = ctx.fingerprint()
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
        if not force and ledger.is_current(original, sha, fingerprint, engine_id, session.redacted_dir):
            return ItemResult(original, redacted, "unchanged", verify_file(dst, PurePosixPath(redacted), ctx))
        tmp = dst.with_name(dst.name + ".part")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        try:
            result = engine.redact(src, tmp, ctx)
            tmp.replace(dst)
        except EngineError as exc:
            tmp.unlink(missing_ok=True)
            return ItemResult(original, redacted, "error", error=str(exc))
        except Exception as exc:  # never surface messages that might quote content
            tmp.unlink(missing_ok=True)
            return ItemResult(original, redacted, "error", error=f"{type(exc).__name__} in engine {engine.name}")
        verdict = verify_file(dst, PurePosixPath(redacted), ctx)
        ledger.record(
            LedgerEntry(
                original, redacted, sha, fingerprint, engine_id, "done", datetime.now(UTC).isoformat(timespec="seconds")
            )
        )
        return ItemResult(original, redacted, "redacted", verdict, remote_calls=result.remote_calls)

    items: list[ItemResult] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for res in pool.map(work, plan):
            items.append(res)
            done += 1
            if progress:
                progress(done, total)
    ledger.save()
    return RunReport(items, context_changed=changed)


def verify_session(session: Session, ctx: RedactionContext) -> list[FileVerdict]:
    """Verify every file currently in ``redacted/``."""
    root = session.redacted_dir
    return [verify_file(p, p.relative_to(root), ctx) for p in sorted(root.rglob("*")) if p.is_file()]
