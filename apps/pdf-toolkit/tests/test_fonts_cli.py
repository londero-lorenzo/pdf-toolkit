"""``pdf-toolkit fonts scan``: statuses, exit codes, and no file name or text on the console."""

import csv

from pdf_core.testing import make_cff_pdf, make_pdf, stream, write_pdf
from pdf_fonts import FontEntry, FontIssue, FontKind, FontReport
from pdf_toolkit.cli import main
from pdf_toolkit.fonts_module import assess

NAME = "Jane Example"


def cli(config, *args):
    return main(["--config", str(config), *args])


def image_only_pdf(path):
    """One page with no font: what a scan looks like to the checks."""
    return write_pdf(
        path,
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << >> /Contents 4 0 R >>",
            stream(b"", b""),
        ],
    )


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
    assert "OK   file#1: 1 page, 1 font\n" in out.out
    assert "NOTE file#2: 1 page, 1 font; 1 CFF with its own encoding (p1): decoded through fontTools" in out.out
    assert "--- 2 files: 1 OK, 1 NOTE, 0 RISK" in out.out
    assert "RISK  text missing or unreadable" in out.out  # legend


def test_show_paths_prints_the_path_under_each_line(tmp_path, config, capsys):
    folder = tmp_path / "docs"
    make_pdf(folder / "sub" / f"{NAME} letter.pdf", [["x"]])
    assert cli(config, "fonts", "scan", str(folder), "--show-paths") == 0
    out = capsys.readouterr().out
    assert f"OK   file#1: 1 page, 1 font\n     sub/{NAME} letter.pdf\n" in out


def test_pdf_without_text_is_a_risk(tmp_path, config, capsys):
    image_only_pdf(tmp_path / "scan.pdf")
    assert cli(config, "fonts", "scan", str(tmp_path)) == 2
    out = capsys.readouterr().out
    assert "RISK file#1: 1 page, 0 fonts; no text on any page (scan or images only): check visually" in out


def test_csv_report_holds_the_paths(tmp_path, config, capsys):
    pdf = make_cff_pdf(tmp_path / f"{NAME}.pdf", [NAME])
    report = tmp_path / "private" / "fonts.csv"
    assert cli(config, "fonts", "scan", str(pdf), "--csv", str(report)) == 0
    assert NAME not in capsys.readouterr().out
    with open(report, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter=";"))
    assert rows[0]["path"] == f"{NAME}.pdf"
    assert rows[0]["status"] == "NOTE"
    assert rows[0]["pages"] == "1"
    assert rows[0]["type1c"] == "1"
    assert rows[0]["cff-custom-encoding"] == "1"
    assert rows[0]["pages without text"] == ""


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
    def entry(*issues, pages=(1,)):
        return FontEntry(FontKind.TYPE0, frozenset(issues), pages)

    cff = FontReport([entry(FontIssue.CFF_CUSTOM_ENCODING, pages=(1, 2, 3, 5))], page_count=5, textless_pages=[4])
    assert assess(cff, fonttools=True) == (
        "RISK",
        "5 pages, 1 font; no text on p4 (scanned page, image or blank): check visually;"
        " 1 CFF with its own encoding (p1-3, p5): decoded through fontTools",
    )
    cff.textless_pages = []
    assert assess(cff, fonttools=True)[0] == "NOTE"
    assert assess(cff, fonttools=False)[0] == "RISK"
    blind = FontReport([entry(FontIssue.NO_UNICODE_MAP, pages=(2,)), entry(FontIssue.NOT_EMBEDDED)], page_count=2)
    assert assess(blind, fonttools=True) == (
        "RISK",
        "2 pages, 2 fonts; 1 without Unicode map (p2): text unreadable, check visually;"
        " 1 not embedded (look only, text unaffected)",
    )
    assert assess(FontReport([entry(FontIssue.NOT_EMBEDDED)], page_count=1), fonttools=True)[0] == "OK"
    assert assess(FontReport(encrypted=True), fonttools=True)[0] == "RISK"
