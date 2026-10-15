from pathlib import PurePosixPath

import pytest

from pdf_redaction.names import NameRedactor, SafePathMapper
from pdf_redaction.rules.context import RedactionContext
from pdf_redaction.rules.terms import Alias, Term
from redaction_fixtures import PERSON, POLICY


@pytest.fixture
def no_alias(source):
    (source / ".redaction" / "aliases.csv").unlink()
    return RedactionContext.load(source, default_packs=["common", "it"])


@pytest.mark.parametrize(
    ("original", "expected"),
    [
        (f"Customer_Profile_n.{POLICY}-{PERSON}", "Customer_Profile_n.REDACTED-REDACTED"),
        ("future_benefit__51740263", "future_benefit_REDACTED"),
        ("statement_2025-12", "statement_2025-12"),
        ("report_20251201", "report_20251201"),
        ("Example_Jane", "REDACTED"),
        ("CON", "_CON"),
        ("a:b?c", "abc"),
    ],
)
def test_folder_names(no_alias, original, expected):
    assert NameRedactor(no_alias).redact_component(original, keep_suffix=False) == expected


def test_file_names_keep_extension(no_alias):
    r = NameRedactor(no_alias)
    assert r.redact_component(f"ABCDE{POLICY}.pdf", keep_suffix=True) == "REDACTED.pdf"
    assert r.redact_component("statement_2025-12.pdf", keep_suffix=True) == "statement_2025-12.pdf"


def test_alias_in_names(ctx):
    r = NameRedactor(ctx)
    assert r.redact_component(f"Customer_Profile_n.{POLICY}-{PERSON}", keep_suffix=False) == (
        "Customer_Profile_n.POL-A-REDACTED"
    )
    assert r.redact_component(f"ABCDE{POLICY}.pdf", keep_suffix=True) == "ABCDEPOL-A.pdf"


@pytest.fixture
def person_alias():
    # the same person as an alias and as a term, plus a term for the surname alone
    return RedactionContext(
        aliases=[Alias(PERSON.lower(), "client_a", "folder-alias#2")],
        terms=[Term(PERSON, "folder#2"), Term("Example", "folder#3")],
    )


@pytest.mark.parametrize(
    ("original", "expected"),
    [
        (f"Contract Profile {PERSON}", "Contract Profile client_a"),
        ("Contract_Profile_Example_Jane", "Contract_Profile_client_a"),
        ("Contract.Profile.Jane.Example", "Contract.Profile.client_a"),
        ("Example, Jane - notes", "client_a - notes"),
        ("JaneExample", "client_a"),
        ("ContractJaneExample", "Contractclient_a"),
        ("JANEEXAMPLE_2025-12", "client_a_2025-12"),
        ("Jane Example_123456789", "client_a_REDACTED"),
        ("Example notes", "REDACTED notes"),
        ("contractjaneexample", "contractjaneexample"),
    ],
)
def test_alias_wins_over_terms_and_matches_variants(person_alias, original, expected):
    r = NameRedactor(person_alias)
    out = r.redact_component(original, keep_suffix=False)
    assert out == expected
    assert r.findings(out) == []


def test_mapper_collisions_and_stability(no_alias):
    m = SafePathMapper(no_alias)
    a = m.map(PurePosixPath(f"x/{PERSON}.pdf"))
    b = m.map(PurePosixPath("x/Example Jane.pdf"))
    c = m.map(PurePosixPath("x/REDACTED.pdf"))
    assert (a.name, b.name, c.name) == ("REDACTED.pdf", "REDACTED_2.pdf", "REDACTED_3.pdf")
    assert m.map(PurePosixPath(f"x/{PERSON}.pdf")) == a  # idempotent


def test_findings_on_clean_name(ctx):
    assert NameRedactor(ctx).findings("Customer_Profile_n.POL-A-REDACTED") == []
    labels = [label for label, _ in NameRedactor(ctx).findings(f"{PERSON}_123456789")]
    assert "term folder#2" in labels and "LONG_DIGIT_CODE_IN_NAME" in labels
