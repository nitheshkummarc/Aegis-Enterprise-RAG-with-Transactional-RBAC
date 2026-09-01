# Aegis — Evaluation Results

**Status: not yet run. This file contains no measurements.**

## Current state

The evaluation harness cannot run because embedding requests are rejected.
`text-embedding-3-small` returns HTTP 403 (`project does not have access to
model`) for the configured OpenAI project. Every golden-dataset question needs
a query embedding, and seeding the corpus needs embeddings for every chunk, so
both are blocked until model access is enabled on that project.

Everything else in the pipeline is verified working:

| Component | Status |
|---|---|
| Database | PostgreSQL 17.6, pgvector 0.8.2, reachable |
| Generation — `openai/gpt-oss-120b` | Answers from context; emits the exact refusal string |
| Generation — `qwen/qwen3.6-27b` | Answers from context; emits the exact refusal string |
| Langfuse tracing | Trace, retrieval span, and nested generation observation confirmed |
| Test suite | 105 passing, including the live-database RBAC test |
| Embeddings | Blocked (HTTP 403) |

## No prior baseline exists

Generation moved from OpenAI `gpt-4o-mini` to Groq. A model change invalidates
every generation-dependent metric, so no earlier figure applies.

Two figures have circulated for this project: 22/22 permission compliance and
8/8 boundary cases. Neither was produced by the current harness, and neither
is possible against it. [`eval/golden_dataset.json`](../eval/golden_dataset.json)
holds **25 questions, 11 of them boundary cases and 3 adversarial**, so a
complete run reports out of 25 and 11.

The last figures committed to this file (25/25, 11/11, faithfulness 1.00, in
commit `c3cf9be`) came from an earlier harness that approximated retrieval
with keyword matching instead of calling the pipeline. They were removed when
the harness was rewritten and do not describe the current system.

## Producing the results

Enable `text-embedding-3-small` for the OpenAI project, then confirm the
vector width matches the schema:

```bash
cd backend
python -m scripts.verify_embedding_dimensions
```

Then seed and run each model:

```bash
python -m scripts.seed_users
python -m scripts.generate_synthetic_corpus

GROQ_MODEL=openai/gpt-oss-120b python -m eval.run_eval
cp eval/results/latest.json eval/results/groq-gpt-oss-120b.json

GROQ_MODEL=qwen/qwen3.6-27b   python -m eval.run_eval
cp eval/results/latest.json eval/results/groq-qwen3.6-27b.json
```

`run_eval.py` overwrites this file and `eval/results/latest.json` on every
run, so copy each result aside before running the next model. Each report
records the generation and embedding models that produced it, in both the JSON
summary and the report table.

## Interpreting the output

**Permission compliance is expected to read 25/25 for both models.** It is
scored from `min_role_level` on a direct call to `permission_filtered_search`
and does not depend on the language model. A lower figure indicates a
regression in the authorization boundary and should be investigated before any
other result is considered.

**Faithfulness and the boundary/refusal rate are the figures affected by the
model change**, and are the basis for choosing a default model. The 11 refusal
cases require the exact string `"I do not have access to that information."`

Before treating a low score as a model regression, check `had_error_event` in
`latest.json`. The harness records a generation error as a faithfulness
failure, so rate limiting appears as poor model performance.

`openai/gpt-oss-120b` is a production model on Groq. `qwen/qwen3.6-27b` is
listed as preview, which Groq documents as suitable for evaluation only and
subject to withdrawal at short notice. That difference is relevant to the
default-model decision alongside the measured scores.
