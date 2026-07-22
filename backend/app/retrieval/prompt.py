"""Strict system prompt for the RAG generation step.

Exact text from Section 5 of the Master Build Prompt. Do not modify
the wording — the eval harness checks for the exact refusal string.
"""

SYSTEM_PROMPT_TEMPLATE = """You are an enterprise assistant. Answer the user's question using ONLY the
provided context below. If the answer is not explicitly present in the
context, reply exactly with: "I do not have access to that information."
Do not use outside knowledge. Do not speculate.

Context:
{context}

Question: {question}"""


def build_prompt(context: str, question: str) -> str:
    """Build the final prompt with context and question injected."""
    return SYSTEM_PROMPT_TEMPLATE.format(context=context, question=question)
