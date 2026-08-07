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
    """Build the final prompt with context and question injected.

    Uses Template-style substitution to avoid Python format-string injection.
    If user input contains '{context}' or '{question}', str.format() would
    raise KeyError or leak variable names. Manual replacement is immune to this.
    """
    # Do NOT use SYSTEM_PROMPT_TEMPLATE.format() — user-controlled content
    # in `question` or `context` could contain {braces} that .format()
    # would try to resolve, causing KeyError or information leakage.
    result = SYSTEM_PROMPT_TEMPLATE.replace("{context}", context)
    result = result.replace("{question}", question)
    return result
