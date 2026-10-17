"""Manual edits of redacted files survive later runs while rules are only added."""

import csv
import json

import pytest

from pdf_core import extract_text
from pdf_core.testing import make_pdf
from pdf_redaction.engines.stirling import StirlingEngine
from pdf_redaction.engines.text import TextEngine
from pdf_redaction.manual import DROP_NO_REBASE, DROP_ORIGINAL_CHANGED, DROP_RULES_REMOVED, ManualStore
from pdf_redaction.pipeline import discard_manual_edits, run_session
from pdf_redaction.publish import EDITED_REASON, publish
from pdf_redaction.rules.context import RedactionContext, context_dir
from pdf_redaction.rules.terms import write_terms
from pdf_redaction.session import Session
from redaction_fixtures import PERSON, FakeStirling, ReferenceEngine

STATEMENT = "Customer_Profile_n.POL-A-REDACTED/statement_2025-12.pdf"
STATEMENT_ORIGINAL_NAME = "statement_2025-12.pdf"
BOX = "[BOX DRAWN BY HAND]"  # stands for a box drawn in a PDF viewer
VALUE = "12.345,67"


@pytest.fixture
def session(tmp_path, source):
    return Session.create(source, tmp_path / "private" / "ws", "sample-2025")


@pytest.fixture
def engine():
    return ReferenceEngine()


def load(source):
    return RedactionContext.load(source, default_packs=["common", "it"])


def run(session, source, engine, **kw):
    return run_session(session, load(source), {"reference": engine, "text": TextEngine()}, **kw)


def edit_by_hand(path):
    """Cover the value line, as a person would with a box in a viewer, and save over the file."""
    lines = [BOX if VALUE in line else line for line in extract_text(path).splitlines() if line.strip()]
    make_pdf(path, [lines])


def item(report, redacted=STATEMENT):
    return next(i for i in report.items if i.redacted == redacted)


def test_adding_a_term_keeps_the_manual_edit(session, source, engine):
    run(session, source, engine)
    edit_by_hand(session.redacted_dir / STATEMENT)
    write_terms(context_dir(source) / "terms.txt", [PERSON, "Holder"])
    before = len(engine.sources)
    report = run(session, source, engine)
    text = extract_text(session.redacted_dir / STATEMENT)
    assert BOX in text and VALUE not in text and "Holder" not in text
    assert report.manual_found == 1 and report.manual_rebuilt == 1
    assert item(report).manual and item(report).outcome == "redacted"
    # files run in parallel, so look for the manual copy among this run's sources, not at the end
    assert ManualStore(session).file_for(item(report).original) in engine.sources[before:]
    # repeatable: the next run with the same rules leaves it alone and still reports it as manual
    again = run(session, source, engine)
    assert item(again).outcome == "unchanged" and item(again).manual and again.manual_found == 0


def test_a_fresh_edit_is_processed_even_if_nothing_else_changed(session, source, engine):
    run(session, source, engine)
    calls = engine.calls
    edit_by_hand(session.redacted_dir / STATEMENT)
    report = run(session, source, engine)
    assert engine.calls == calls + 1 and item(report).outcome == "redacted" and item(report).manual
    assert report.count("unchanged") == 2  # the other files were not touched


def test_force_keeps_the_manual_edit(session, source, engine):
    run(session, source, engine)
    edit_by_hand(session.redacted_dir / STATEMENT)
    run(session, source, engine)
    run(session, source, engine, force=True)
    assert BOX in extract_text(session.redacted_dir / STATEMENT)


def test_removing_a_rule_drops_the_edit_but_keeps_its_copy(session, source, engine):
    write_terms(context_dir(source) / "terms.txt", [PERSON, "Holder"])
    run(session, source, engine)
    edit_by_hand(session.redacted_dir / STATEMENT)
    write_terms(context_dir(source) / "terms.txt", [PERSON])
    report = run(session, source, engine)
    assert item(report).manual_dropped == DROP_RULES_REMOVED and not item(report).manual
    assert report.manual_dropped == {DROP_RULES_REMOVED: 1}
    assert BOX not in extract_text(session.redacted_dir / STATEMENT)
    store = ManualStore(session)
    (original,) = store.entries
    assert store.entries[original].stale == DROP_RULES_REMOVED
    assert BOX in extract_text(store.file_for(original))  # still there to look at
    # adding the rule back does not revive a stale edit
    write_terms(context_dir(source) / "terms.txt", [PERSON, "Holder"])
    assert not item(run(session, source, engine)).manual


def test_a_changed_original_drops_the_edit(session, source, engine):
    run(session, source, engine)
    edit_by_hand(session.redacted_dir / STATEMENT)
    original = next(source.rglob(STATEMENT_ORIGINAL_NAME))
    make_pdf(original, [[f"Holder: {PERSON}", "Value 1,00 EUR"]])
    session.sync_originals()
    report = run(session, source, engine)
    assert item(report).manual_dropped == DROP_ORIGINAL_CHANGED
    assert BOX not in extract_text(session.redacted_dir / STATEMENT)


def test_engines_without_rule_digests_drop_the_edit(session, source, engine):
    run(session, source, engine)
    path = session.redacted_dir / "movements.csv"
    path.write_text(path.read_text(encoding="utf-8") + "edited;by;hand\n", encoding="utf-8")
    report = run(session, source, engine)
    assert item(report, "movements.csv").manual_dropped == DROP_NO_REBASE
    assert "edited;by;hand" not in path.read_text(encoding="utf-8")


def test_edit_is_captured_before_a_new_name_removes_the_old_output(session, source, engine):
    run(session, source, engine)
    edit_by_hand(session.redacted_dir / STATEMENT)
    write_terms(context_dir(source) / "terms.txt", [PERSON, "statement"])
    report = run(session, source, engine)
    (moved,) = [i for i in report.items if i.manual]
    assert moved.redacted != STATEMENT and not (session.redacted_dir / STATEMENT).exists()
    assert BOX in extract_text(session.redacted_dir / moved.redacted)


def test_publish_holds_back_an_edit_until_a_run_processed_it(tmp_path, session, source, engine):
    run(session, source, engine)
    edit_by_hand(session.redacted_dir / STATEMENT)
    out = tmp_path / "shared"
    assert dict(publish(session, load(source), out).blocked)[STATEMENT] == EDITED_REASON
    run(session, source, engine)
    report = publish(session, load(source), out)
    assert STATEMENT in report.published and BOX in extract_text(out / STATEMENT)


def test_discard_redoes_the_file_from_the_original(session, source, engine):
    run(session, source, engine)
    edit_by_hand(session.redacted_dir / STATEMENT)
    run(session, source, engine)
    assert discard_manual_edits(session, ["movements.csv"]) == 0
    assert discard_manual_edits(session, [STATEMENT]) == 1
    assert not any(session.manual_dir.rglob("*.pdf"))
    report = run(session, source, engine)
    assert item(report).outcome == "redacted" and not item(report).manual
    assert BOX not in extract_text(session.redacted_dir / STATEMENT)


def test_discard_of_an_edit_not_yet_processed(session, source, engine):
    run(session, source, engine)
    edit_by_hand(session.redacted_dir / STATEMENT)
    assert discard_manual_edits(session) == 1
    report = run(session, source, engine)
    assert report.manual_found == 0 and item(report).outcome == "redacted"
    assert BOX not in extract_text(session.redacted_dir / STATEMENT)


def strip_new_ledger_columns(session):
    with open(session.ledger_path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    old_fields = [f for f in rows[0] if f not in ("output_sha256", "base")]
    with open(session.ledger_path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=old_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def test_older_ledgers_are_never_treated_as_edited(session, source, engine):
    run(session, source, engine)
    strip_new_ledger_columns(session)
    edit_by_hand(session.redacted_dir / STATEMENT)  # made before the upgrade: cannot be told apart
    report = run(session, source, engine)
    assert report.manual_found == 0 and item(report).outcome == "unchanged"


def test_older_ledgers_detect_edits_made_after_the_first_run(session, source, engine):
    run(session, source, engine)
    strip_new_ledger_columns(session)
    run(session, source, engine)  # unchanged files get their output hash
    edit_by_hand(session.redacted_dir / STATEMENT)
    report = run(session, source, engine)
    assert report.manual_found == 1 and item(report).manual


def test_workspace_files_hold_no_rule_in_clear(session, source, engine):
    run(session, source, engine)
    edit_by_hand(session.redacted_dir / STATEMENT)
    run(session, source, engine)
    assert "Jane" not in session.rulesets_path.read_text(encoding="utf-8")
    rulesets = json.loads(session.rulesets_path.read_text(encoding="utf-8"))
    assert len(rulesets) == 1  # only the fingerprint the ledger still refers to
    # manual.json is keyed by original path, like ledger.csv (private workspace); rules are digests
    (edit,) = json.loads(session.manual_path.read_text(encoding="utf-8")).values()
    assert "Jane" not in json.dumps(edit) and all(len(d) == 64 for d in edit["rules"])


def test_stirling_sanitizes_and_rebuilds_on_the_edit(tmp_path, session, source, server):
    key = tmp_path / "key.txt"
    key.write_text(FakeStirling.api_key, encoding="utf-8")
    stirling = StirlingEngine({"url": server, "api_key_file": str(key)})
    engines = {"stirling": stirling, "text": TextEngine()}
    run_session(session, load(source), engines)
    edit_by_hand(session.redacted_dir / STATEMENT)
    FakeStirling.requests = []
    write_terms(context_dir(source) / "terms.txt", [PERSON, "Holder"])
    report = run_session(session, load(source), engines)
    assert item(report).manual
    paths = sorted(r["path"] for r in FakeStirling.requests)
    assert paths.count("/api/v1/security/auto-redact") == 2  # both PDFs: the rules changed
    assert paths.count("/api/v1/security/sanitize-pdf") == 2
    uploaded = [r["files"]["fileInput"][1] for r in FakeStirling.requests if r["path"].endswith("auto-redact")]
    manual_copy = next(session.manual_dir.rglob("*.pdf")).read_bytes()
    assert manual_copy in uploaded
    text = extract_text(session.redacted_dir / STATEMENT)
    assert BOX in text and "Holder" not in text
