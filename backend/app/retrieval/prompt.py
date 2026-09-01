"""System prompt template for the generation step.

The evaluation harness matches the refusal sentence exactly, so the wording
must not be changed.
"""

import re

SYSTEM_PROMPT_TEMPLATE = """You are an enterprise assistant. Answer the user's question using ONLY the
provided context below. If the answer is not explicitly present in the
context, reply exactly with: "I do not have access to that information."
Do not use outside knowledge. Do not speculate.

Context:
{context}

Question: {question}"""


def build_prompt(context: str, question: str) -> str:
    """Insert context and question into the prompt template.

    Both placeholders are substituted in a single pass. str.format() is not
    used because braces in user input would raise or expose variable names,
    and sequential str.replace() calls would allow a placeholder appearing in
    the context to be overwritten by the question.
    """
    replacements = {"{context}": context, "{question}": question}
    pattern = re.compile("|".join(re.escape(k) for k in replacements))
    return pattern.sub(lambda m: replacements[m.group(0)], SYSTEM_PROMPT_TEMPLATE)
