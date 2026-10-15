from concurrent.futures import ThreadPoolExecutor

import pytest

from pdf_core import available_backends, extract_text, inspect_pdf
from pdf_core.testing import make_cff_pdf, make_pdf


@pytest.fixture
def sample(tmp_path):
    return make_pdf(
        tmp_path / "sample.pdf",
        [["Quarterly statement", "Holder: Jane Example"], ["Second page", "Total 1.234,56"]],
        image_pages=[2],
        info={"Author": "Jane Example", "Title": "Statement"},
    )


@pytest.mark.parametrize("backend", available_backends())
def test_pages_text_and_images(sample, backend):
    report = inspect_pdf(sample, backend)
    assert [p.number for p in report.pages] == [1, 2]
    assert "Jane Example" in report.pages[0].text
    assert report.image_pages == [2]
    assert "Jane Example" in report.metadata_text
    assert report.has_text
    assert not report.encrypted


@pytest.mark.parametrize("backend", available_backends())
def test_backends_can_be_used_from_several_threads(sample, backend):
    with ThreadPoolExecutor(max_workers=4) as pool:
        reports = list(pool.map(lambda _: inspect_pdf(sample, backend), range(40)))
    assert all(r.image_pages == [2] for r in reports)


def test_text_chunks_cover_metadata(sample):
    where = [w for w, _ in inspect_pdf(sample).text_chunks()]
    assert where[:2] == ["p1", "p2"]
    assert "metadata" in where


def test_extract_text_joins_pages(sample):
    assert extract_text(sample).count("\f") == 1


def test_unknown_backend(sample):
    with pytest.raises(ValueError):
        inspect_pdf(sample, "nope")


@pytest.fixture
def cff_sample(tmp_path):
    return make_cff_pdf(tmp_path / "cff.pdf", ["Holder Jane Example", "Code AB-1234"])


@pytest.mark.parametrize("backend", available_backends())
def test_cff_font_with_custom_encoding_is_decoded(cff_sample, backend):
    text = extract_text(cff_sample, backend)
    assert "Jane Example" in text
    assert "AB-1234" in text


def test_without_fonttools_pypdf_cannot_decode_cff_fonts(cff_sample, monkeypatch):
    # why fonttools is a dependency: without it the custom encoding is lost and a term to find
    # would go unnoticed
    import pypdf.generic._font

    monkeypatch.setattr(pypdf.generic._font, "HAS_FONTTOOLS", False)
    assert "Jane Example" not in extract_text(cff_sample, "pypdf")
