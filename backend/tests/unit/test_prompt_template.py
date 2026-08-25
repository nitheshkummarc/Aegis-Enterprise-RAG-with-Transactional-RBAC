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

    def test_context_containing_literal_question_placeholder_is_not_double_substituted(self):
        """A retrieved chunk that literally contains the substring
        "{question}" must NOT have that occurrence overwritten by the live
        question — two sequential .replace() calls would leak the question
        into what should be static document content."""
        context = "The FAQ template field is literally named {question} in our CMS."
        question = "What does the CMS field contain?"

        result = build_prompt(context=context, question=question)

        # The context's literal "{question}" text must survive untouched.
        assert (
            "The FAQ template field is literally named {question} in our CMS."
            in result
        )
        # The real question must still appear exactly once, in its own slot.
        assert result.count(question) == 1

    def test_context_containing_literal_context_placeholder_is_not_double_substituted(self):
        """Same guard for a chunk that literally contains "{context}"."""
        context = "Our template uses a {context} variable for injection."
        question = "How does templating work?"

        result = build_prompt(context=context, question=question)

        assert "Our template uses a {context} variable for injection." in result
        assert result.count(question) == 1
