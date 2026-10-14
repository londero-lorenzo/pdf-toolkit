from pathlib import PurePosixPath

from pdf_core.testing import make_pdf
from pdf_redaction.engines.text import TextEngine
from pdf_redaction.rules.context import FolderSettings, RedactionContext, context_dir
from pdf_redaction.verify import Status, verify_file
from redaction_fixtures import PERSON, POLICY, TAX_CODE


def test_pdf_with_term_fails_without_quoting_it(tmp_path, ctx):
    pdf = make_pdf(tmp_path / "a.pdf", [[f"Holder {PERSON}"], ["clean"]])
    v = verify_file(pdf, PurePosixPath("a.pdf"), ctx)
    assert v.status is Status.FAIL
    assert any(f.where == "p1" and f.rule == "term folder#2" for f in v.findings)
    assert PERSON not in v.summary()


def test_metadata_is_checked(tmp_path, ctx):
    pdf = make_pdf(tmp_path / "a.pdf", [["clean text"]], info={"Author": PERSON})
    v = verify_file(pdf, PurePosixPath("a.pdf"), ctx)
    assert v.status is Status.FAIL and any(f.where == "metadata" for f in v.findings)


def test_clean_pdf_ok_and_images_warn(tmp_path, ctx):
    assert verify_file(make_pdf(tmp_path / "a.pdf", [["clean"]]), PurePosixPath("a.pdf"), ctx).status is Status.OK
    v = verify_file(make_pdf(tmp_path / "b.pdf", [["clean"]], image_pages=[1]), PurePosixPath("b.pdf"), ctx)
    assert v.status is Status.WARN and v.image_pages == [1]


def test_scanned_pdf_warns(tmp_path, ctx):
    v = verify_file(make_pdf(tmp_path / "s.pdf", [[]], image_pages=[1]), PurePosixPath("s.pdf"), ctx)
    assert v.status is Status.WARN and any("no extractable text" in n for n in v.notes)


def test_name_in_path_fails(tmp_path, ctx):
    pdf = make_pdf(tmp_path / "a.pdf", [["clean"]])
    v = verify_file(pdf, PurePosixPath(f"{PERSON}/a.pdf"), ctx)
    assert v.status is Status.FAIL and v.path_has_hits


def test_unsupported_type_fails(tmp_path, ctx):
    (tmp_path / "x.docx").write_bytes(b"PK")
    assert verify_file(tmp_path / "x.docx", PurePosixPath("x.docx"), ctx).status is Status.FAIL


def test_csv_engine_redacts_cells_and_drops_columns(tmp_path, source):
    FolderSettings(drop_columns=("amount",)).save(context_dir(source) / "settings.toml")
    ctx = RedactionContext.load(source, default_packs=["common", "it"])
    out = tmp_path / "out.csv"
    res = TextEngine().redact(source / "movements.csv", out, ctx)
    text = out.read_text(encoding="utf-8")
    assert PERSON not in text and "amount" not in text and "[REDACTED]" in text
    assert res.counts["term folder#2"] == 2
    assert verify_file(out, PurePosixPath("out.csv"), ctx).status is Status.OK


def test_csv_first_and_last_name_in_adjacent_columns(tmp_path, ctx):
    first, last = PERSON.split()
    f = tmp_path / "people.csv"
    f.write_text(f"first;last\n{first};{last}\n", encoding="utf-8")
    assert verify_file(f, PurePosixPath("people.csv"), ctx).status is Status.FAIL


def test_text_engine_plain_text(tmp_path, ctx):
    src = tmp_path / "n.txt"
    src.write_text(f"policy {POLICY}, tax code {TAX_CODE}", encoding="utf-8")
    TextEngine().redact(src, tmp_path / "o.txt", ctx)
    assert (tmp_path / "o.txt").read_text(encoding="utf-8") == "policy POL-A, tax code [REDACTED]"
