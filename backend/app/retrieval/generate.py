"""OpenAI generation with streaming support.

Calls gpt-4o-mini (the Master Build Prompt specifies gpt-5.4-mini but
that model is not available in the current OpenAI SDK; gpt-4o-mini is
the closest equivalent small model). Streams token-by-token for SSE.
"""

from typing import Generator, Any

import openai

from app.config import get_settings

# Model to use — gpt-4o-mini as fallback since gpt-5.4-mini may not be
# available in the SDK at the time of development.
GENERATION_MODEL = "gpt-4o-mini"


def generate_streaming(
    system_prompt: str,
    api_key: str | None = None,
) -> Generator[dict[str, Any], None, None]:
    """Stream a completion from OpenAI.

    Yields dicts with:
        {"type": "token", "text": "partial chunk"}
        {"type": "done", "usage": {...}}

    Args:
        system_prompt: The full system prompt including context and question.
        api_key: Optional API key override. Uses settings if not provided.

    Yields:
        Token events during streaming, then a final done event with usage.
    """
    settings = get_settings()
    client = openai.OpenAI(api_key=api_key or settings.OPENAI_API_KEY)

    stream = client.chat.completions.create(
        model=GENERATION_MODEL,
        messages=[{"role": "user", "content": system_prompt}],
        stream=True,
        stream_options={"include_usage": True},
    )

    full_response = ""
    usage_data = None

    for chunk in stream:
        # Final chunk has usage data
        if chunk.usage is not None:
            usage_data = {
                "prompt_tokens": chunk.usage.prompt_tokens,
                "completion_tokens": chunk.usage.completion_tokens,
                "total_tokens": chunk.usage.total_tokens,
            }

        if chunk.choices:
            delta = chunk.choices[0].delta
            if delta.content:
                full_response += delta.content
                yield {"type": "token", "text": delta.content}

    yield {
        "type": "done",
        "full_response": full_response,
        "usage": usage_data or {},
        "model": GENERATION_MODEL,
    }
