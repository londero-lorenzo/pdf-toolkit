import hashlib
import json
import subprocess

import pytest

from pdf_redaction.audit import audit_repo
from pdf_redaction.engines.text import TextEngine
from pdf_redaction.guards import GuardError
from pdf_redaction.pipeline import plan_names, run_session
from pdf_redaction.publish import publish
from pdf_redaction.rules.context import RedactionContext, context_dir
from pdf_redaction.rules.terms import write_terms
from pdf_redaction.session import Session
from pdf_redaction.verify import Status
from redaction_fixtures import PERSON, POLICY, LeakyEngine, ReferenceEngine


def tree_hash(root):
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file() and ".redaction" not in p.parts:
            h.update(p.relative_to(root).as_posix().encode() + p.read_bytes())
    return h.hexdigest()


@pytest.fixture
def session(tmp_path, source):
    return Session.create(source, tmp_path / "private" / "ws", "sample-2025")


def test_guards(tmp_path, source):
    with pytest.raises(GuardError):
        Session.create(source, source / "ws", "a")  # workspace inside source
    with pytest.raises(GuardError):
        Session.create(source, tmp_path / "shared" / "ws", "a", protected=[tmp_path / "shared"])
    with pytest.raises(GuardError):
        Session.create(source, tmp_path / "ws", "bad alias/..")


def test_copy_excludes_context_and_keeps_source(session, source):
    manifest = session.manifest()
    assert len(manifest) == 4 and not any(k.startswith(".redaction") for k in manifest)
    before = tree_hash(source)
    (source / "movements.csv").unlink()
    result = session.sync_originals()
    assert result.removed == 1 and len(session.manifest()) == 3
    assert tree_hash(source) != before  # we deleted it ourselves; the sync never writes to source


def test_full_run_redacts_names_and_contents(session, source, ctx, engines):
    before = tree_hash(source)
    report = run_session(session, ctx, engines, workers=2)
    assert tree_hash(source) == before
    by_outcome = {i.redacted: i for i in report.items}
    assert set(by_outcome) == {
        "ABCDEPOL-A.pdf",
        "Customer_Profile_n.POL-A-REDACTED/statement_2025-12.pdf",
        "movements.csv",
        "notes.docx",
    }
    assert by_outcome["notes.docx"].outcome == "unsupported"
    assert by_outcome["movements.csv"].verdict.status is Status.OK
    assert by_outcome["Customer_Profile_n.POL-A-REDACTED/statement_2025-12.pdf"].verdict.status is Status.OK
    assert by_outcome["ABCDEPOL-A.pdf"].verdict.status is Status.WARN  # image on the page
    for p in session.redacted_dir.rglob("*"):
        assert PERSON not in p.as_posix() and POLICY not in p.as_posix()


def test_incremental_and_context_change(session, source, ctx):
    engine = ReferenceEngine()
    engines = {"reference": engine, "text": TextEngine()}
    run_session(session, ctx, engines)
    assert engine.calls == 2
    report = run_session(session, ctx, engines)
    assert engine.calls == 2 and report.count("unchanged") == 3
    write_terms(context_dir(source) / "terms.txt", [PERSON, "Annual report"])
    ctx2 = RedactionContext.load(source, default_packs=["common", "it"])
    report = run_session(session, ctx2, engines)
    assert report.context_changed == 3 and engine.calls == 4


def test_leaky_engine_is_caught(session, ctx):
    report = run_session(session, ctx, {"leaky": LeakyEngine(), "text": TextEngine()})
    statuses = {i.redacted: i.verdict.status for i in report.items if i.verdict}
    assert statuses["Customer_Profile_n.POL-A-REDACTED/statement_2025-12.pdf"] is Status.FAIL


def test_publish_rules(tmp_path, session, ctx, engines):
    run_session(session, ctx, engines)
    out = tmp_path / "shared"
    report = publish(session, ctx, out)
    assert "ABCDEPOL-A.pdf" in dict(report.blocked)  # WARN, not reviewed yet
    assert (out / "sample-2025" / "movements.csv").exists()
    assert (out / "sample-2025" / "_text" / "Customer_Profile_n.POL-A-REDACTED" / "statement_2025-12.pdf.txt").exists()
    session.set_reviewed(["ABCDEPOL-A.pdf"])
    report = publish(session, ctx, out)
    assert "ABCDEPOL-A.pdf" in report.published
    published = json.loads((out / "sample-2025" / ".published.json").read_text(encoding="utf-8"))
    assert "ABCDEPOL-A.pdf" in published
    for p in out.rglob("*"):
        if p.is_file():
            assert PERSON not in p.read_text(encoding="utf-8", errors="ignore")


def test_review_is_lost_when_the_file_changes(session, ctx, engines):
    run_session(session, ctx, engines)
    session.set_reviewed(["ABCDEPOL-A.pdf"])
    assert session.reviewed() == {"ABCDEPOL-A.pdf"}
    run_session(session, ctx, engines, force=True)  # same content: the review still holds
    assert session.reviewed() == {"ABCDEPOL-A.pdf"}
    with open(session.redacted_dir / "ABCDEPOL-A.pdf", "ab") as fh:
        fh.write(b"%changed")
    assert session.reviewed() == set()
    session.set_reviewed(["ABCDEPOL-A.pdf"], False)
    assert json.loads(session.review_path.read_text(encoding="utf-8")) == {}


def test_publish_blocks_fail_and_stale_context(tmp_path, session, source, ctx):
    run_session(session, ctx, {"leaky": LeakyEngine(), "text": TextEngine()})
    report = publish(session, ctx, tmp_path / "shared")
    assert dict(report.blocked)["Customer_Profile_n.POL-A-REDACTED/statement_2025-12.pdf"] == "verification FAIL"
    write_terms(context_dir(source) / "terms.txt", [PERSON, "x y"])
    ctx2 = RedactionContext.load(source, default_packs=["common", "it"])
    report = publish(session, ctx2, tmp_path / "shared")
    assert all("rules changed" in reason for _, reason in report.blocked)


def test_publish_blocks_files_whose_source_changed(tmp_path, session, source, ctx, engines):
    run_session(session, ctx, engines)
    with open(source / "movements.csv", "a", encoding="utf-8") as fh:
        fh.write("2025-03-31;someone;300,00\n")
    session.sync_originals()  # the next run starts like this; suppose it then fails on this file
    report = publish(session, ctx, tmp_path / "shared")
    assert dict(report.blocked)["movements.csv"] == "source changed since it was redacted: run again"


def test_publish_refuses_output_inside_workspace(session, ctx, engines):
    run_session(session, ctx, engines)
    with pytest.raises(GuardError):
        publish(session, ctx, session.workspace / "out")


def test_plan_names_is_deterministic(session, ctx):
    assert plan_names(session, ctx) == plan_names(session, ctx)


def test_audit_repo(tmp_path, ctx):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "ok.py").write_text("print('hello')\n", encoding="utf-8")
    (repo / "leak.md").write_text(f"author: {PERSON}\n", encoding="utf-8")
    (repo / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (repo / "ignored.txt").write_text(PERSON, encoding="utf-8")
    verdicts = {v.rel_path: v.status for v in audit_repo(repo, ctx)}
    assert verdicts == {".gitignore": Status.OK, "leak.md": Status.FAIL, "ok.py": Status.OK}
