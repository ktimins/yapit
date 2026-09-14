"""Tests for PDF page analysis and the free extraction path on scanned pages."""

import pymupdf
import pytest

from yapit.gateway.document.pdf import estimate_document_tokens, is_scanned_page
from yapit.gateway.document.processors import free_pdf

A4_PT = (595, 842)
LETTER_PT = (612, 792)
A4_300DPI = (2480, 3508)


def _blank_image(width: int, height: int) -> pymupdf.Pixmap:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, width, height))
    pix.clear_with(255)
    return pix


def _scanned_book_page(page_pt: tuple[int, int] = A4_PT) -> pymupdf.Document:
    """A page the way archive.org builds them: a full-page image plus an invisible OCR text layer."""
    doc = pymupdf.open()
    page = doc.new_page(width=page_pt[0], height=page_pt[1])
    page.insert_image(page.rect, pixmap=_blank_image(*A4_300DPI))
    page.insert_text((72, 100), "Recognized text from the scan", render_mode=3)
    return doc


def _text_page_with_figure(figure_px: tuple[int, int]) -> pymupdf.Document:
    doc = pymupdf.open()
    page = doc.new_page(width=A4_PT[0], height=A4_PT[1])
    page.insert_text((72, 100), "Body text")
    page.insert_image(pymupdf.Rect(72, 150, 372, 450), pixmap=_blank_image(*figure_px))
    return doc


def test_scanned_page_is_detected_from_image_shape():
    assert is_scanned_page(_scanned_book_page(), 0) is True


def test_a4_scan_on_letter_page_is_still_a_scan():
    assert is_scanned_page(_scanned_book_page(LETTER_PT), 0) is True


def test_page_shaped_figure_below_scan_resolution_is_not_a_scan():
    # Same aspect ratio as the page, but 400 px wide is ~50 dpi on A4
    assert is_scanned_page(_text_page_with_figure((400, 566)), 0) is False


def test_scanned_page_estimates_as_raster_even_with_ocr_text():
    content = _scanned_book_page().tobytes()
    estimate = estimate_document_tokens(content, "application/pdf", 1)
    assert estimate.raster_pages == 1
    assert estimate.text_pages == 0


@pytest.mark.asyncio
async def test_free_extraction_keeps_the_ocr_text_of_a_scanned_page():
    content = _scanned_book_page().tobytes()
    pages = [result.page async for result in free_pdf.extract(content)]
    assert pages[0] is not None
    assert "Recognized text from the scan" in pages[0].markdown
