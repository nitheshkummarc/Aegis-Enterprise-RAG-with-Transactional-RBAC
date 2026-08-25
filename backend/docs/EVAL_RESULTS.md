# ClearanceRAG — Evaluation Results

**Status: pending re-run.**

The eval harness ([`eval/run_eval.py`](../eval/run_eval.py)) was rewritten to
call the real `/retrieval/query` endpoint end-to-end — real OpenAI query
embedding, real `permission_filtered_search` against pgvector, real
`gpt-4o-mini` generation — and to score permission compliance and
faithfulness against the model's actual output, including checking that
boundary/refusal cases produce the exact required refusal string.

The numbers previously shown here were produced by an earlier version of the
harness that approximated retrieval with keyword matching instead of calling
the real pipeline, so they've been removed rather than left in place under a
methodology they no longer reflect.

To regenerate this report with real numbers:

```bash
cd backend
python -m scripts.seed_users
python -m scripts.generate_synthetic_corpus   # requires an OpenAI embedding model enabled
python -m eval.run_eval                       # requires OPENAI_API_KEY with embedding + gpt-4o-mini access
```

`run_eval.py` overwrites this file and `eval/results/latest.json` on every run.
