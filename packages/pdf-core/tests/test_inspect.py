import pytest

from pdf_core import available_backends, extract_text, inspect_pdf
from pdf_core.testing import make_pdf


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


def test_text_chunks_cover_metadata(sample):
    where = [w for w, _ in inspect_pdf(sample).text_chunks()]
    assert where[:2] == ["p1", "p2"]
    assert "metadata" in where


def test_extract_text_joins_pages(sample):
    assert extract_text(sample).count("\f") == 1


def test_unknown_backend(sample):
    with pytest.raises(ValueError):
        inspect_pdf(sample, "nope")
