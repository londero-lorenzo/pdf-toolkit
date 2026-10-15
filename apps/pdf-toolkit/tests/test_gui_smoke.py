"""The GUI builds, opens a session, runs it and shows results (skipped without a display)."""

import gc
import time

import pytest

from pdf_toolkit import redaction_service as svc
from pdf_toolkit.config import AppConfig
from redaction_fixtures import PERSON, POLICY

tk = pytest.importorskip("tkinter")


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    r.withdraw()
    yield r
    r.destroy()
    del r
    gc.collect()  # free Tk objects here, in the main thread, not later inside a worker thread


def wait_idle(tab, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        tab.update()
        if not tab._busy:
            return
        time.sleep(0.02)
    raise TimeoutError


def test_shell_and_redaction_tab(root, config, source, capsys):
    from pdf_toolkit.gui.redaction import RedactionTab
    from pdf_toolkit.gui.shell import Shell

    cfg = AppConfig.load(config)
    Shell(root, cfg)
    svc.create_session(cfg, source, "gui-test")
    tab = RedactionTab(root, cfg)
    tab.open_session("gui-test")
    wait_idle(tab)
    tab.run()
    wait_idle(tab)
    statuses = sorted(tab.tree.set(i, "status") for i in tab.tree.get_children())
    assert statuses == ["OK", "OK", "SKIP", "WARN"]
    first = tab.tree.get_children()[0]
    tab.tree.selection_set(first)
    tab.mark_reviewed(True)
    assert tab.tree.set(first, "reviewed") == "yes"
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""


def test_context_editor_keeps_comments(root, config, source):
    from pdf_toolkit.gui.redaction.context_editor import ContextEditor

    cfg = AppConfig.load(config)
    terms = f"# Clients\n{PERSON}\n\n# Codes\n{POLICY}"
    aliases = f"# Contracts\n\n{POLICY} ; POL-A"
    editor = ContextEditor(root, cfg, source)
    for box, text in ((editor.terms, terms), (editor.aliases, aliases)):
        box.delete("1.0", "end")
        box.insert("1.0", text)
    editor.save()
    reopened = ContextEditor(root, cfg, source)
    assert reopened.terms.get("1.0", "end-1c") == terms
    assert reopened.aliases.get("1.0", "end-1c") == aliases
    reopened.destroy()


def test_manual_edits_are_marked_and_can_be_discarded(root, config, source):
    from pdf_core.testing import make_pdf
    from pdf_toolkit.gui.redaction import RedactionTab

    cfg = AppConfig.load(config)
    session = svc.create_session(cfg, source, "gui-manual")
    tab = RedactionTab(root, cfg)
    tab.open_session("gui-manual")
    wait_idle(tab)
    tab.run()
    wait_idle(tab)
    statement = "Customer_Profile_n.POL-A-REDACTED/statement_2025-12.pdf"
    make_pdf(session.redacted_dir / statement, [["[BOX DRAWN BY HAND]"]])
    tab.verify()
    wait_idle(tab)
    rows = {tab.tree.set(i, "path"): i for i in tab.tree.get_children()}
    assert svc.MANUAL_PENDING in tab.tree.set(rows[statement], "details")
    tab.run()
    wait_idle(tab)
    rows = {tab.tree.set(i, "path"): i for i in tab.tree.get_children()}
    assert svc.MANUAL_KEPT in tab.tree.set(rows[statement], "details")
    tab.tree.selection_set(rows[statement])
    tab.discard_manual(confirm=False)
    assert "1 manual edit(s) discarded" in tab.summary.cget("text")
