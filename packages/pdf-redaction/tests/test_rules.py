import re

import pytest

from pdf_redaction.rules.context import FolderSettings, RedactionContext, context_dir
from pdf_redaction.rules.java_regex import to_java_patterns
from pdf_redaction.rules.patterns import available_packs, get_patterns
from pdf_redaction.rules.terms import load_aliases, load_terms, term_regex, write_terms
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


def test_java_patterns_are_valid_python_and_cover_terms(ctx):
    patterns = to_java_patterns(ctx)
    assert patterns[0].startswith("(?iu:")
    combined = re.compile("|".join(patterns))
    for value in (PERSON, POLICY, TAX_CODE, EMAIL):
        assert combined.search(value)
    assert not any("(?P" in p for p in patterns)
