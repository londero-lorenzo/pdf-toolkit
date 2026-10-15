import re

import pytest

from pdf_redaction.rules.context import FolderSettings, RedactionContext, context_dir
from pdf_redaction.rules.java_regex import to_java_patterns, to_python, to_stirling_dialect, unsupported_by_stirling
from pdf_redaction.rules.patterns import available_packs, get_patterns
from pdf_redaction.rules.terms import (
    ALIASES_HEADER,
    TERMS_HEADER,
    load_aliases,
    load_terms,
    parse_aliases_text,
    read_aliases_text,
    read_terms_text,
    term_regex,
    write_aliases,
    write_terms,
    write_terms_text,
)
from pdf_redaction.textredact import TextRedactor
from redaction_fixtures import EMAIL, PERSON, POLICY, TAX_CODE


@pytest.mark.parametrize("text", ["Jane Example", "EXAMPLE  Jane", "Jane\nExample", "Jane Example"])
def test_name_any_order_and_spacing(text):
    assert term_regex(PERSON).search(text)


def test_name_needs_word_boundary():
    assert not term_regex("Ann").search("Annual report")


@pytest.mark.parametrize("text", ["009 9988 8777-666/555", "00999888777666555", "n.00999888777666555"])
def test_code_with_separators(text):
    assert term_regex(POLICY).search(text)


def test_code_unbounded_for_names():
    assert not term_regex(POLICY).search(f"ABCDE{POLICY}")
    assert term_regex(POLICY, bounded=False).search(f"ABCDE{POLICY}")


@pytest.mark.parametrize("text", ["JaneExample", "ExampleJane", "JANEEXAMPLE", "ContractJaneExample", "JaneExampleCv"])
def test_name_joined_or_camel_case_in_file_names(text):
    assert term_regex(PERSON, bounded=False).search(text)
    assert not term_regex(PERSON).search(text)  # contents and Stirling keep the strict rule


@pytest.mark.parametrize("text", ["contractjaneexample", "Planjane example", "PlannLeeway"])
def test_name_unbounded_still_needs_a_boundary(text):
    assert not term_regex(PERSON, bounded=False).search(text)
    assert not term_regex("Ann Lee", bounded=False).search(text)


def test_patterns_it_pack():
    names = {p.name for p in get_patterns(["common", "it"])}
    assert {"EMAIL", "IBAN", "TAX_CODE_IT", "IBAN_IT", "MOBILE_PHONE_IT"} <= names
    assert set(available_packs()) >= {"common", "it"}
    with pytest.raises(ValueError):
        get_patterns(["xx"])


def test_text_redactor(ctx):
    r = TextRedactor(ctx)
    out = r.apply(f"{PERSON} - {POLICY} - {TAX_CODE} - {EMAIL} - IT60 X054 2811 1010 0000 0123 456")
    for value in (PERSON, POLICY, TAX_CODE, EMAIL, "IT60"):
        assert value not in out
    assert "POL-A" in out
    assert r.counts["TAX_CODE_IT"] == 1


def test_load_terms_and_aliases(tmp_path):
    (tmp_path / "t.txt").write_text("# comment\nJane Example\njane example\n\nACME-123\n", encoding="utf-8")
    terms = load_terms(tmp_path / "t.txt", "global")
    assert [t.label for t in terms] == ["global#2", "global#5"]
    (tmp_path / "a.csv").write_text("real;alias\n123456789;POL-B\n", encoding="utf-8")
    assert [(a.real, a.alias) for a in load_aliases(tmp_path / "a.csv", "x")] == [("123456789", "POL-B")]


def test_terms_text_round_trip_keeps_comments_and_blank_lines(tmp_path):
    text = f"# Clients\n{PERSON}\n\n# Contracts\n{POLICY}\n{PERSON.lower()}"
    write_terms_text(tmp_path / "t.txt", text + "\n\n")
    assert read_terms_text(tmp_path / "t.txt") == text
    assert [(t.value, t.label) for t in load_terms(tmp_path / "t.txt", "folder")] == [
        (PERSON, "folder#2"),
        (POLICY, "folder#5"),
    ]


def test_empty_terms_text_writes_the_header(tmp_path):
    write_terms_text(tmp_path / "t.txt", "\n \n")
    assert read_terms_text(tmp_path / "t.txt") == TERMS_HEADER
    assert load_terms(tmp_path / "t.txt", "folder") == []


def test_aliases_text_round_trip_keeps_comments_and_blank_lines(tmp_path):
    text = f"# Clients\n\n{PERSON} ; Client A\n# Contracts; misc; notes\n{POLICY} ; POL-A"
    write_aliases(tmp_path / "a.csv", parse_aliases_text(text + "\n\n"), header=False)
    assert read_aliases_text(tmp_path / "a.csv") == text
    assert [(a.real, a.alias, a.label) for a in load_aliases(tmp_path / "a.csv", "folder-alias")] == [
        (PERSON, "Client A", "folder-alias#3"),
        (POLICY, "POL-A", "folder-alias#5"),
    ]


def test_new_aliases_file_starts_with_a_comment_not_a_csv_header(tmp_path):
    write_aliases(tmp_path / "a.csv", [(POLICY, "POL-A")])
    lines = (tmp_path / "a.csv").read_text(encoding="utf-8").splitlines()
    assert lines == [ALIASES_HEADER, f"{POLICY},POL-A"]
    assert [(a.real, a.label) for a in load_aliases(tmp_path / "a.csv", "x")] == [(POLICY, "x#2")]


def test_empty_aliases_text_writes_only_the_header(tmp_path):
    write_aliases(tmp_path / "a.csv", parse_aliases_text("\n \n"), header=False)
    assert read_aliases_text(tmp_path / "a.csv") == ALIASES_HEADER
    assert load_aliases(tmp_path / "a.csv", "x") == []


def test_legacy_aliases_header_is_dropped_on_save(tmp_path):
    (tmp_path / "a.csv").write_text(f"real,alias\n{POLICY},POL-A\n", encoding="utf-8")
    text = read_aliases_text(tmp_path / "a.csv")
    assert text == f"{POLICY} ; POL-A"
    write_aliases(tmp_path / "a.csv", parse_aliases_text(text), header=False)
    assert (tmp_path / "a.csv").read_text(encoding="utf-8").splitlines() == [f"{POLICY},POL-A"]


def test_alias_comments_do_not_change_the_delimiter(tmp_path):
    (tmp_path / "a.csv").write_text("# a; b; c; d\nreal,alias\n123456789,POL-B\n", encoding="utf-8")
    assert [(a.real, a.alias) for a in load_aliases(tmp_path / "a.csv", "x")] == [("123456789", "POL-B")]
    assert read_aliases_text(tmp_path / "a.csv") == "# a; b; c; d\n123456789 ; POL-B"


def test_aliases_header_after_comments_is_not_an_alias(tmp_path):
    (tmp_path / "a.csv").write_text("# note\n\nreal;alias\n123456789;POL-B\n", encoding="utf-8")
    assert [(a.real, a.label) for a in load_aliases(tmp_path / "a.csv", "x")] == [("123456789", "x#4")]


def test_malformed_alias_line_names_only_the_line_number():
    with pytest.raises(ValueError) as err:
        parse_aliases_text(f"# ok\n{PERSON} ; Client A\n{POLICY} POL-A")
    assert str(err.value).startswith("Line 3:")
    assert POLICY not in str(err.value)


def test_context_merges_global_and_folder(tmp_path, source):
    write_terms(tmp_path / "global.txt", ["Global Person", PERSON])
    FolderSettings(pattern_packs=("common",), drop_columns=("holder",)).save(context_dir(source) / "settings.toml")
    ctx = RedactionContext.load(source, global_term_files=[tmp_path / "global.txt"], default_packs=["common", "it"])
    assert ctx.counts() == {"terms": 2, "aliases": 1, "patterns": 3}
    assert ctx.drop_columns == ("holder",)
    assert [t.label for t in ctx.terms] == ["global#2", "global#3"]


def test_fingerprint_changes_with_rules(source, ctx):
    before = ctx.fingerprint()
    write_terms(context_dir(source) / "terms.txt", [PERSON, "Another Name"])
    after = RedactionContext.load(source, default_packs=["common", "it"]).fingerprint()
    assert before != after


def test_java_patterns_use_the_stirling_dialect_and_cover_terms(ctx):
    patterns = to_java_patterns(ctx)
    assert patterns[0].startswith("(?i:")
    assert not any(unsupported_by_stirling(p) or "(?P" in p for p in patterns)
    assert any(r"\x{a0}" in p for p in patterns)
    combined = re.compile("|".join(to_python(p) for p in patterns))
    for value in (PERSON, POLICY, TAX_CODE, EMAIL, "Jane Example", "EXAMPLE  JANE"):
        assert combined.search(value)


def test_stirling_dialect_rewrites_and_rejects():
    assert to_stirling_dialect(r"a[\s\u00a0]b") == r"a[\s\x{a0}]b"
    assert to_stirling_dialect(r"a\\u00a0") == r"a\\u00a0"  # escaped backslash followed by "u00a0"
    assert to_python(r"a[\s\x{a0}]b") == r"a[\s\u00a0]b"
    for bad in (r"(?iu:abc)", r"(?u)abc"):
        with pytest.raises(ValueError):
            to_stirling_dialect(bad)
