"""``pdf-toolkit fonts scan``: statuses, exit codes, and no file name or text on the console."""

import csv

from pdf_core.testing import make_cff_pdf, make_pdf
from pdf_fonts import FontReport
from pdf_toolkit.cli import main
from pdf_toolkit.fonts_module import assess

NAME = "Jane Example"


def cli(config, *args):
    return main(["--config", str(config), *args])


def test_scan_folder_prints_counts_only(tmp_path, config, capsys):
    folder = tmp_path / "docs"
    make_pdf(folder / f"{NAME} letter.pdf", [[NAME]])
    make_cff_pdf(folder / "sub" / f"{NAME} form.pdf", [NAME])
    make_pdf(folder / ".redaction" / "ignored.pdf", [["x"]])
    (folder / "notes.txt").write_text(NAME, encoding="utf-8")

    assert cli(config, "fonts", "scan", str(folder)) == 0
    out = capsys.readouterr()
    assert NAME not in out.out + out.err
    assert "fontTools: installed" in out.out
    assert "OK   file#1: 1 fonts" in out.out
    assert "NOTE file#2: 1 fonts; 1 CFF with its own encoding (p1): decoded through fontTools" in out.out
    assert "--- 2 files: 1 OK, 1 NOTE, 0 RISK" in out.out


def test_csv_report_holds_the_paths(tmp_path, config, capsys):
    pdf = make_cff_pdf(tmp_path / f"{NAME}.pdf", [NAME])
    report = tmp_path / "private" / "fonts.csv"
    assert cli(config, "fonts", "scan", str(pdf), "--csv", str(report)) == 0
    assert NAME not in capsys.readouterr().out
    with open(report, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter=";"))
    assert rows[0]["path"] == f"{NAME}.pdf"
    assert rows[0]["status"] == "NOTE"
    assert rows[0]["type1c"] == "1"
    assert rows[0]["cff-custom-encoding"] == "1"


def test_csv_report_refused_in_protected_location(tmp_path, config, capsys):
    pdf = make_pdf(tmp_path / "a.pdf", [["x"]])
    code = cli(config, "fonts", "scan", str(pdf), "--csv", str(tmp_path / "shared" / "fonts.csv"))
    assert code == 1 and "protected location" in capsys.readouterr().err


def test_missing_path_is_reported_by_position(tmp_path, config, capsys):
    assert cli(config, "fonts", "scan", str(tmp_path / NAME)) == 1
    err = capsys.readouterr().err
    assert "PATH #1 does not exist" in err and NAME not in err


def test_unreadable_pdf_is_a_risk(tmp_path, config, capsys):
    (tmp_path / f"{NAME}.pdf").write_bytes(b"not a pdf")
    assert cli(config, "fonts", "scan", str(tmp_path)) == 2
    out = capsys.readouterr().out
    assert "RISK file#1: unreadable (" in out and NAME not in out


def test_assess_statuses():
    from pdf_fonts import FontEntry, FontIssue, FontKind

    def entry(*issues, pages=(1,)):
        return FontEntry(FontKind.TYPE0, frozenset(issues), pages)

    cff = FontReport([entry(FontIssue.CFF_CUSTOM_ENCODING, pages=(1, 2, 3, 5))])
    assert assess(cff, fonttools=True) == (
        "NOTE",
        "1 fonts; 1 CFF with its own encoding (p1-3, p5): decoded through fontTools",
    )
    assert assess(cff, fonttools=False)[0] == "RISK"
    blind = FontReport([entry(FontIssue.NO_UNICODE_MAP, pages=(2,)), entry(FontIssue.NOT_EMBEDDED)])
    assert assess(blind, fonttools=True) == (
        "RISK",
        "2 fonts; 1 without Unicode map (p2): extracted text unreliable, check visually; 1 not embedded",
    )
    assert assess(FontReport(encrypted=True), fonttools=True)[0] == "RISK"
