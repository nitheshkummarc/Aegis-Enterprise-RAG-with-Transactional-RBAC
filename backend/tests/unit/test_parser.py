"""Unit tests for PDF text/table extraction."""

import os
import tempfile
from unittest.mock import patch, MagicMock

import fitz
import pytest

from app.ingestion.parser import extract_text_from_pdf


def _save_pdf(build_fn) -> str:
    """Build a PDF via `build_fn(doc, page)` and save it to a temp file,
    returning the path. Caller is responsible for cleanup."""
    doc = fitz.open()
    page = doc.new_page()
    build_fn(doc, page)
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    doc.save(path)
    doc.close()
    return path


class TestExtractTextFromPdf:
    def test_extracts_plain_text(self):
        path = _save_pdf(
            lambda doc, page: page.insert_text((50, 50), "Hello world.")
        )
        try:
            text = extract_text_from_pdf(path)
            assert "Hello world." in text
        finally:
            os.remove(path)

    def test_corrupt_pdf_raises_runtime_error(self):
        fd, path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        with open(path, "wb") as f:
            f.write(b"NOT A PDF")
        try:
            with pytest.raises(RuntimeError):
                extract_text_from_pdf(path)
        finally:
            os.remove(path)

    def test_extracts_table_as_markdown_with_rows_matching_headers(self):
        def build(doc, page):
            page.insert_text((50, 50), "Q3 Regional Performance")
            rows = [
                ["Region", "Packages", "Growth"],
                ["Chicago", "1.2M", "12%"],
                ["Dallas", "0.8M", "-3%"],
            ]
            x0, y0, col_w, row_h = 50, 100, 100, 20
            for r, row in enumerate(rows):
                for c, val in enumerate(row):
                    page.insert_text((x0 + c * col_w, y0 + r * row_h), val)
            for r in range(len(rows) + 1):
                page.draw_line(
                    (x0 - 5, y0 - 15 + r * row_h),
                    (x0 - 5 + 3 * col_w, y0 - 15 + r * row_h),
                )
            for c in range(4):
                page.draw_line(
                    (x0 - 5 + c * col_w, y0 - 15),
                    (x0 - 5 + c * col_w, y0 - 15 + len(rows) * row_h),
                )

        path = _save_pdf(build)
        try:
            text = extract_text_from_pdf(path)
            # A value must stay associated with its row's other cells,
            # not just present somewhere in the flattened text.
            assert "| Chicago | 1.2M | 12% |" in text
            assert "| Dallas | 0.8M | -3% |" in text
            assert "| Region | Packages | Growth |" in text
        finally:
            os.remove(path)

    def test_table_detection_failure_does_not_break_plain_text(self):
        path = _save_pdf(
            lambda doc, page: page.insert_text((50, 50), "Fallback text works.")
        )
        try:
            with patch.object(
                fitz.Page, "find_tables", side_effect=RuntimeError("boom")
            ):
                text = extract_text_from_pdf(path)
            assert "Fallback text works." in text
        finally:
            os.remove(path)

    def test_no_tables_on_page_adds_nothing(self):
        path = _save_pdf(
            lambda doc, page: page.insert_text((50, 50), "Just prose, no table.")
        )
        try:
            text = extract_text_from_pdf(path)
            assert "|" not in text
        finally:
            os.remove(path)
