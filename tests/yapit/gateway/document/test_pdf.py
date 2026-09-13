"""Tests for PDF page analysis and the free extraction path on scanned pages."""

import pymupdf

from yapit.gateway.document.pdf import estimate_document_tokens, is_scanned_page
from yapit.gateway.document.processors.free_pdf import _extract_page

A4_PT = (595, 842)


def _blank_image(width: int, height: int) -> pymupdf.Pixmap:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, width, height))
    pix.clear_with(255)
    return pix


def _scanned_book_page() -> pymupdf.Document:
    """A page the way archive.org builds them: a full-page image plus an invisible OCR text layer."""
    doc = pymupdf.open()
    page = doc.new_page(width=A4_PT[0], height=A4_PT[1])
    page.insert_image(page.rect, pixmap=_blank_image(2480, 3508))
    page.insert_text((72, 100), "Recognized text from the scan", render_mode=3)
    return doc


def _born_digital_page_with_figure() -> pymupdf.Document:
    doc = pymupdf.open()
    page = doc.new_page(width=A4_PT[0], height=A4_PT[1])
    page.insert_text((72, 100), "Body text")
    page.insert_image(pymupdf.Rect(72, 150, 372, 450), pixmap=_blank_image(1200, 1200))
    return doc


def test_scanned_page_is_detected_from_image_shape():
    assert is_scanned_page(_scanned_book_page(), 0) is True


def test_figure_on_text_page_is_not_a_scan():
    assert is_scanned_page(_born_digital_page_with_figure(), 0) is False


def test_scanned_page_estimates_as_raster_even_with_ocr_text():
    content = _scanned_book_page().tobytes()
    estimate = estimate_document_tokens(content, "application/pdf", 1)
    assert estimate.raster_pages == 1
    assert estimate.text_pages == 0


def test_free_extraction_keeps_ocr_text_and_drops_the_image():
    text = _extract_page(_scanned_book_page()[0])
    assert "Recognized text from the scan" in text
