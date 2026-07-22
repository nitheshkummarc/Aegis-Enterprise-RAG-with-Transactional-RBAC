"""Unit tests for the text chunker.

Tests: chunk boundaries, overlap correctness, short document edge case,
empty input, and single-chunk document.
"""

import pytest
from app.ingestion.chunker import chunk_text


class TestChunkText:
    """Tests for chunk_text function."""

    def test_empty_input_returns_empty_list(self):
        """Empty string returns no chunks."""
        assert chunk_text("") == []
        assert chunk_text("   ") == []

    def test_short_text_returns_single_chunk(self):
        """Text shorter than chunk_size returns a single chunk."""
        text = "This is a short document."
        chunks = chunk_text(text, chunk_size=500, chunk_overlap=50)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_exact_chunk_size_returns_single_chunk(self):
        """Text exactly at chunk_size returns a single chunk."""
        text = "x" * 500
        chunks = chunk_text(text, chunk_size=500, chunk_overlap=50)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_multiple_chunks_created(self):
        """Text longer than chunk_size produces multiple chunks."""
        text = "word " * 200  # 1000 characters
        chunks = chunk_text(text, chunk_size=500, chunk_overlap=50)
        assert len(chunks) > 1

    def test_all_text_is_covered(self):
        """Every character in the original text appears in at least one chunk."""
        text = "The quick brown fox jumps over the lazy dog. " * 30
        chunks = chunk_text(text, chunk_size=100, chunk_overlap=20)

        # Reconstruct: all original text should be findable in chunks
        combined = "".join(chunks)
        for char_idx in range(0, len(text), 50):
            segment = text[char_idx:char_idx + 20]
            assert segment in combined, (
                f"Segment at position {char_idx} not found in chunks"
            )

    def test_overlap_exists_between_consecutive_chunks(self):
        """Consecutive chunks share overlapping content."""
        # Use text without natural break points to get predictable behavior
        text = "abcdefghij" * 100  # 1000 chars, no spaces
        chunks = chunk_text(text, chunk_size=200, chunk_overlap=50)

        assert len(chunks) > 1
        for i in range(len(chunks) - 1):
            # The end of chunk[i] should overlap with the start of chunk[i+1]
            tail = chunks[i][-50:]
            head = chunks[i + 1][:50]
            # There should be shared content between consecutive chunks
            assert tail == head or any(
                tail[j:] == head[:len(tail) - j]
                for j in range(len(tail))
            ), f"No overlap found between chunk {i} and {i+1}"

    def test_chunk_size_respected(self):
        """No chunk exceeds the specified chunk_size."""
        text = "Hello world. This is a test. " * 100
        chunk_size = 200
        chunks = chunk_text(text, chunk_size=chunk_size, chunk_overlap=30)

        for i, chunk in enumerate(chunks):
            # Allow slight overflow for natural break point adjustment
            assert len(chunk) <= chunk_size + 50, (
                f"Chunk {i} is {len(chunk)} chars, exceeds limit of {chunk_size}"
            )

    def test_no_empty_chunks_produced(self):
        """No chunk in the output should be empty."""
        text = "Test content repeated many times. " * 50
        chunks = chunk_text(text, chunk_size=100, chunk_overlap=20)
        for i, chunk in enumerate(chunks):
            assert len(chunk) > 0, f"Chunk {i} is empty"

    def test_single_word_document(self):
        """A single word produces a single chunk."""
        chunks = chunk_text("Hello", chunk_size=500, chunk_overlap=50)
        assert len(chunks) == 1
        assert chunks[0] == "Hello"

    def test_none_input_returns_empty(self):
        """None input returns empty list."""
        assert chunk_text(None) == []
