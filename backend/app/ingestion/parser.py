"""PyMuPDF-based PDF text extraction.

Extracts prose text and detected tables (rendered as markdown, so rows and
columns stay coherent) from each page.
"""

import fitz  # PyMuPDF


def extract_text_from_pdf(file_path: str) -> str:
    """Extract text content from a PDF file.

    Args:
        file_path: Path to the PDF file.

    Returns:
        Concatenated text from all pages. Detected tables are appended
        per-page as markdown — page.get_text() reads a table cell-by-cell
        left-to-right, top-to-bottom as flat prose, which detaches values
        from their row/column labels (a revenue-by-region table becomes an
        unlabeled run of numbers). The markdown rendering keeps each row's
        cells associated with their header, giving chunking/embedding a
        coherent version of the table to work with.

    Raises:
        RuntimeError: If the PDF cannot be opened or is corrupt.
    """
    try:
        doc = fitz.open(file_path)
    except Exception as e:
        raise RuntimeError(f"Failed to open PDF '{file_path}': {e}") from e

    pages: list[str] = []
    try:
        for page in doc:
            page_text = page.get_text()
            tables_markdown = _extract_tables_as_markdown(page)
            if tables_markdown:
                page_text = f"{page_text}\n\n{tables_markdown}"
            pages.append(page_text)
    except Exception as e:
        raise RuntimeError(f"Failed to extract text from PDF '{file_path}': {e}") from e
    finally:
        doc.close()

    return "\n".join(pages)


def _extract_tables_as_markdown(page: "fitz.Page") -> str:
    """Render any tables detected on `page` as markdown.

    Best-effort: table detection is heuristic, so a page it gets wrong or
    can't parse must never break plain text extraction for that page.
    """
    try:
        tables = page.find_tables()
    except Exception:
        return ""

    blocks = []
    for table in tables:
        try:
            rows = table.extract()
        except Exception:
            continue
        if not rows or not rows[0]:
            continue

        header, *body = rows
        blocks.append(_rows_to_markdown([_cell_text(c) for c in header], body))

    return "\n\n".join(blocks)


def _rows_to_markdown(header: list[str], body: list[list]) -> str:
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for row in body:
        cells = [_cell_text(c) for c in row]
        # Pad/truncate to the header width so a ragged row can't break the
        # markdown table structure.
        cells = (cells + [""] * len(header))[: len(header)]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _cell_text(value) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ").strip()
