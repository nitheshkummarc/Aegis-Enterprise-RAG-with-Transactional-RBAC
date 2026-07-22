"""Unit tests for the system prompt template."""

import pytest

from app.retrieval.prompt import SYSTEM_PROMPT_TEMPLATE, build_prompt


class TestPromptTemplate:
    """Tests for the prompt template."""

    def test_template_contains_context_placeholder(self):
        """Template has a {context} placeholder."""
        assert "{context}" in SYSTEM_PROMPT_TEMPLATE

    def test_template_contains_question_placeholder(self):
        """Template has a {question} placeholder."""
        assert "{question}" in SYSTEM_PROMPT_TEMPLATE

    def test_template_contains_refusal_string(self):
        """Template instructs the exact refusal string."""
        assert "I do not have access to that information" in SYSTEM_PROMPT_TEMPLATE

    def test_template_forbids_outside_knowledge(self):
        """Template says not to use outside knowledge."""
        assert "Do not use outside knowledge" in SYSTEM_PROMPT_TEMPLATE

    def test_build_prompt_fills_placeholders(self):
        """build_prompt correctly fills context and question."""
        result = build_prompt(
            context="The PTO policy is 15 days annually.",
            question="What is the PTO policy?",
        )
        assert "The PTO policy is 15 days annually." in result
        assert "What is the PTO policy?" in result
        assert "{context}" not in result
        assert "{question}" not in result

    def test_build_prompt_empty_context(self):
        """Empty context still produces a valid prompt."""
        result = build_prompt(context="", question="Tell me something.")
        assert "Tell me something." in result
        assert "Context:" in result
