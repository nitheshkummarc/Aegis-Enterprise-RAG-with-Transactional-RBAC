"""Unit tests for the LangChain/Groq generation layer.

These cover the pieces that have no other guard: the SSE event contract that
five integration tests patch over, the usage-metadata parsing that Groq only
sometimes populates, and the reasoning-token exclusion that the eval
harness's exact refusal-string check depends on.

They deliberately drive ``_stream_tokens`` with hand-built chunks rather than
a live model, so a failure points at the accumulation logic and nothing else.
"""

import pytest
from langchain_core.messages import AIMessageChunk

from app.core.exceptions import ConfigurationError
from app.retrieval.generate import (
    _stream_tokens,
    _usage_from_chunk,
    build_llm,
    generate_streaming,
)


class TestUsageParsing:
    """Groq reports usage only on the final chunk, and sometimes not at all."""

    def test_usage_metadata_maps_to_sse_contract_keys(self):
        chunk = AIMessageChunk(
            content="",
            usage_metadata={
                "input_tokens": 120,
                "output_tokens": 9,
                "total_tokens": 129,
            },
        )
        assert _usage_from_chunk(chunk) == {
            "prompt_tokens": 120,
            "completion_tokens": 9,
            "total_tokens": 129,
        }

    def test_chunk_without_usage_returns_none(self):
        assert _usage_from_chunk(AIMessageChunk(content="hi")) is None


class TestStreamTokens:
    """The yielded event shape is a contract shared with routes.py and the
    eval harness — it must not drift."""

    def test_tokens_then_single_done_event(self):
        events = list(_stream_tokens([
            AIMessageChunk(content="PTO is "),
            AIMessageChunk(content="15 days."),
        ]))

        assert [e["type"] for e in events] == ["token", "token", "done"]
        assert events[-1]["full_response"] == "PTO is 15 days."

    def test_done_event_carries_usage_from_final_chunk(self):
        events = list(_stream_tokens([
            AIMessageChunk(content="answer"),
            AIMessageChunk(
                content="",
                usage_metadata={
                    "input_tokens": 5,
                    "output_tokens": 2,
                    "total_tokens": 7,
                },
            ),
        ]))
        assert events[-1]["usage"] == {
            "prompt_tokens": 5,
            "completion_tokens": 2,
            "total_tokens": 7,
        }

    def test_missing_usage_degrades_to_empty_dict(self):
        """Absent usage is an expected Groq behavior, not a failure: the done
        event must still be well-formed."""
        done = list(_stream_tokens([AIMessageChunk(content="answer")]))[-1]
        assert done["usage"] == {}

    def test_empty_stream_still_yields_exactly_one_done_event(self):
        """routes.py only emits the SSE done event (carrying sources) when it
        sees a done event — a silent model must not swallow it."""
        events = list(_stream_tokens([]))
        assert len(events) == 1
        assert events[0]["type"] == "done"
        assert events[0]["full_response"] == ""

    def test_empty_content_chunks_emit_no_token_events(self):
        events = list(_stream_tokens([
            AIMessageChunk(content=""),
            AIMessageChunk(content="real"),
            AIMessageChunk(content=""),
        ]))
        assert [e["type"] for e in events] == ["token", "done"]

    def test_done_event_reports_the_configured_model(self):
        done = list(_stream_tokens([]))[-1]
        from app.retrieval.generate import active_model_name

        assert done["model"] == active_model_name()

    def test_reasoning_blocks_are_excluded_from_the_token_stream(self):
        """gpt-oss-120b emits reasoning traces. If they reach full_response
        they corrupt the eval harness's exact-substring refusal check, so a
        structured chunk must contribute only its text block."""
        chunk = AIMessageChunk(content=[
            {"type": "reasoning", "reasoning": "Let me check whether the context covers this"},
            {"type": "text", "text": "I do not have access to that information."},
        ])

        done = list(_stream_tokens([chunk]))[-1]

        assert done["full_response"] == "I do not have access to that information."
        assert "Let me check" not in done["full_response"]


class TestMisconfigurationIsLoud:
    """Config faults must raise, never degrade into a generic 502. A silently
    swallowed setup error is exactly how the Langfuse v2/v4 mismatch hid."""

    def test_build_llm_without_api_key_raises(self, monkeypatch):
        monkeypatch.setattr(
            "app.retrieval.generate._require_setting",
            _raise_for("GROQ_API_KEY"),
        )
        with pytest.raises(ConfigurationError, match="GROQ_API_KEY"):
            build_llm()

    def test_generate_streaming_surfaces_config_error_on_first_iteration(
        self, monkeypatch
    ):
        """generate_streaming is a generator, so the failure appears when the
        route starts consuming it, not when it is called."""
        monkeypatch.setattr(
            "app.retrieval.generate.build_llm",
            _raise_for("GROQ_MODEL"),
        )
        stream = generate_streaming("prompt")
        with pytest.raises(ConfigurationError, match="GROQ_MODEL"):
            next(stream)


def _raise_for(name: str):
    def _raiser(*args, **kwargs):
        raise ConfigurationError(f"{name} is not set.")

    return _raiser
