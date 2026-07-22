"""PyMuPDF-based PDF text extraction.

Extracts all text from a PDF file page by page.
"""

import fitz  # PyMuPDF


def extract_text_from_pdf(file_path: str) -> str:
    """Extract text content from a PDF file.

    Args:
        file_path: Path to the PDF file.

    Returns:
        Concatenated text from all pages.

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
            pages.append(page.get_text())
    except Exception as e:
        raise RuntimeError(f"Failed to extract text from PDF '{file_path}': {e}") from e
    finally:
        doc.close()

    return "\n".join(pages)
