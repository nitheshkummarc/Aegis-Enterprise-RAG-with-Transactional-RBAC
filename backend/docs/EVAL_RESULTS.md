# Aegis — Evaluation Results

**Status: not yet run against the Groq generation layer. No numbers below.**

## Why there are no numbers

Generation migrated from a direct OpenAI `gpt-4o-mini` call to LangChain
`ChatGroq`, selected by `GROQ_MODEL`. A model swap invalidates every
generation-dependent metric, so nothing may be carried across it.

Two figures have circulated informally for this project — **22/22 permission
compliance** and **8/8 adversarial/boundary**. Neither has ever been produced
by the current harness, and neither is even arithmetically possible against
it: [`eval/golden_dataset.json`](../eval/golden_dataset.json) holds **25
questions, of which 11 are boundary cases and 3 are adversarial**, so a clean
run reports out of **25** and **11**. The last numbers ever committed
(25/25, 11/11, faithfulness 1.00, commit `c3cf9be`) came from an earlier
harness that approximated retrieval with keyword matching rather than calling
the real pipeline; they were deliberately removed when the harness was
rewritten and must not be reinstated.

There is therefore **no verified baseline of any kind** for this project. The
first Groq run will be the first real measurement it has ever had — a
starting point, not a comparison.

## Blocked on

1. **`GROQ_API_KEY`** — not yet issued. Generation cannot run without it.
2. **Database reachability** — the harness requires a live seeded pgvector
   instance. The configured Supabase pooler currently times out from this
   environment (`tests/integration/test_rbac_end_to_end.py` fails for the same
   reason, and did so before this migration).

## How to produce the numbers

From `backend/`, against a live seeded database:

```bash
python -m scripts.seed_users
python -m scripts.generate_synthetic_corpus   # only if not already seeded
python -m eval.run_eval
```

`run_eval.py` overwrites this file and `eval/results/latest.json` on every
run, so copy the result aside between models or the previous one is lost:

```bash
GROQ_MODEL=openai/gpt-oss-120b python -m eval.run_eval
cp eval/results/latest.json eval/results/groq-gpt-oss-120b.json

GROQ_MODEL=qwen/qwen3.6-27b   python -m eval.run_eval
cp eval/results/latest.json eval/results/groq-qwen3.6-27b.json
```

Each report now records the model that actually produced it, in both the
JSON summary (`generation_model`) and the report's summary table.

## What to expect, stated in advance

**Permission compliance should read 25/25 for both models.** It is scored
from `min_role_level` on a direct call to `permission_filtered_search`, so it
is structurally independent of the LLM — no model swap can move it. If it
moves at all, this migration touched RBAC and must be reverted before
anything else is reviewed.

**Faithfulness and the boundary/refusal rate are the numbers genuinely at
risk**, and are the real criterion for which model becomes the default. The
11 refusal cases require the exact string `"I do not have access to that
information."`; models routinely paraphrase it.

Before treating a poor score as a model regression, check `had_error_event`
in `latest.json`. The harness records a generation error as a faithfulness
failure, so free-tier rate limiting reads as a bad model rather than as
infrastructure.

Note that `qwen/qwen3.6-27b` is a **preview** model on Groq, which states
preview models are for evaluation only and may be withdrawn at short notice;
`openai/gpt-oss-120b` is production. That asymmetry should weigh in the
default-model decision alongside the scores.
