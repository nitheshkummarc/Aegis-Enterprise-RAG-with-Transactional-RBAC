"""Recursive character text splitter for document chunking.

Splits text into chunks of approximately `chunk_size` characters with
`chunk_overlap` characters of overlap between consecutive chunks.
"""


def chunk_text(
    text: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> list[str]:
    """Split text into overlapping chunks.

    Args:
        text: The text to split.
        chunk_size: Target size for each chunk in characters. Must be > 0.
        chunk_overlap: Number of overlapping characters between consecutive
            chunks. Must be >= 0 and < chunk_size.

    Returns:
        A list of text chunks. Returns a single-element list if the text is
        shorter than chunk_size. Returns an empty list for empty input.

    Raises:
        ValueError: If chunk_size <= 0 or chunk_overlap >= chunk_size.
    """
    if chunk_size <= 0:
        raise ValueError(f"chunk_size must be > 0, got {chunk_size}")
    if chunk_overlap < 0:
        raise ValueError(f"chunk_overlap must be >= 0, got {chunk_overlap}")
    if chunk_overlap >= chunk_size:
        raise ValueError(
            f"chunk_overlap ({chunk_overlap}) must be < chunk_size ({chunk_size})"
        )

    if not text or not text.strip():
        return []

    # If the entire text fits in one chunk, return it as-is
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0

    while start < len(text):
        end = start + chunk_size

        # If this is the last chunk, take everything remaining
        if end >= len(text):
            chunks.append(text[start:])
            break

        # Try to break at a natural boundary (newline, then sentence, then word)
        chunk = text[start:end]
        break_point = _find_break_point(chunk)

        if break_point > 0:
            actual_end = start + break_point
        else:
            actual_end = end

        chunks.append(text[start:actual_end])

        # Move start forward by chunk length minus overlap
        next_start = actual_end - chunk_overlap

        # Guard against non-progress: if overlap pushed us backward or
        # to the same position, force forward by at least 1 character
        # to prevent an infinite loop.
        if next_start <= start:
            next_start = start + 1

        start = next_start

    return chunks


def _find_break_point(chunk: str) -> int:
    """Find the best position to break a chunk at a natural boundary.

    Tries, in order: last double-newline, last newline, last period+space,
    last space. Returns 0 if no suitable break point is found.
    """
    separators = ["\n\n", "\n", ". ", " "]

    for sep in separators:
        # Look for the last occurrence in the back third of the chunk
        # to avoid creating very small chunks
        min_pos = len(chunk) // 3
        idx = chunk.rfind(sep, min_pos)
        if idx > 0:
            return idx + len(sep)

    return 0
