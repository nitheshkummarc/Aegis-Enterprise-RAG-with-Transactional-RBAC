# Aegis Methodology

[ARCHITECTURE.md](ARCHITECTURE.md) describes the system.
[ENGINEERING_DECISIONS.md](ENGINEERING_DECISIONS.md) records the decisions
behind it. This document describes how the system is built and how its claims
are verified.

---

## 1. The corpus is synthetic

Evaluating an RBAC system requires knowing the ground truth of who may see
what. Real documents do not come with that label, and mislabeling even one of
them silently corrupts every permission metric computed from it.

`scripts/generate_synthetic_corpus.py` therefore generates the corpus with
known clearance tiers: 10 documents across viewer, manager and admin levels,
each chunked and embedded through the same `app.ingestion.chunker` and
`app.ingestion.embedder` path a real upload would take. The evaluation is
end-to-end over the real pipeline; only the *authorship* of the documents is
synthetic.

Cross-contamination checks matter more than corpus size. If admin-tier facts
also appear in viewer-tier documents, a permission leak cannot be detected,
because the leaked answer would be reachable through permitted content. The
refusal cases depend on facts being exclusive to their tier.

---

## 2. The authorization boundary is tested where it lives

Authorization is enforced in one place: the SQL `WHERE dc.min_role_level <=
:user_role_level` in `app/retrieval/search.py`. The testing follows that,
rather than testing a convenient proxy for it.

| Layer | What it checks | Where |
|---|---|---|
| Unit | The query builder resolves role → numeric level from the JWT claim through a fixed map, never from client input | `tests/unit/test_search_query_builder.py` |
| Security | Role filtering rejects the cases it is supposed to reject | `tests/security/test_rbac_enforcement.py` |
| Integration (real Postgres) | An actual database returns zero admin chunks to a viewer | `tests/integration/test_rbac_end_to_end.py` |
| Evaluation | The full pipeline, per question, per role | `eval/run_eval.py` |

The integration test runs against a real database rather than a mock. A mocked
database confirms only that the application sends the intended SQL; it cannot
confirm that PostgreSQL, pgvector, and the selected index honour the predicate.

The `EXPLAIN (ANALYZE, BUFFERS)` verification in
[ARCHITECTURE.md](ARCHITECTURE.md#verified-query-plan) follows the same
principle: index selection for a bound parameter is a property of the query
plan, not of the SQL text, so it was measured against a live instance. The
execution times from that run are a cache-warming artifact and are documented
as such rather than reported as a performance result.

---

## 3. Evaluation methodology

`eval/run_eval.py` runs every question in `eval/golden_dataset.json` through
the real `/retrieval/query` endpoint using real JWTs minted by the backend's
own `create_access_token`. Nothing in the path is mocked: OpenAI embedding,
pgvector search, Groq generation, and the SSE stream all run for real.

### Dataset composition

**25 questions**, of which **11 are boundary cases** and **3 are adversarial**.
Those denominators are the ones any honest report uses.

### The two metrics measure different things

**Permission compliance** is scored from the `min_role_level` of the chunks
returned by a direct call to `permission_filtered_search`. It asks one
question: *did the database hand back anything above the asking role's level?*
It is structurally independent of the language model. No prompt change, model
swap or decoding setting can move it. This is the metric that speaks to the
security thesis, and it is expected to read **25/25** — anything else means
the authorization boundary itself regressed.

**Faithfulness** is scored against the model's **actual generated text**,
recovered by reassembling the SSE token stream. For the 11 refusal cases it
checks for the exact string `"I do not have access to that information."`

Faithfulness is scored on generated text rather than retrieved chunks because
a chunk-level check cannot distinguish a correct refusal from a model that
ignored its instructions and answered from prior knowledge. Both produce zero
retrieved chunks; only the generated text distinguishes them.

### What each metric cannot tell you

*   Permission compliance says nothing about answer quality. It would read
    25/25 for a model that returns nothing but empty strings.
*   Faithfulness says nothing about security. A model can be perfectly
    faithful to context it should never have received.
*   Neither covers upload-time misclassification. If a document is stamped
    with the wrong `min_role_level` at ingestion, every downstream check
    passes while enforcing the wrong policy. That is a separate concern with
    separate handling.

### Adversarial cases

Three questions carry forged credentials rather than ordinary prompts —
`jwt_escalation` presents a `superadmin` role that does not exist,
`jwt_null` presents a null role. Both must be rejected by the auth layer
before retrieval runs at all. The scoring reflects that: a `4xx` is the pass
condition, because it proves no chunk was ever fetched to leak.

### Latency reporting

Retrieval latency is **DB-only**. The embedding call is deliberately outside
the timer, because mixing a network round-trip to the embedding provider into a metric labelled
"retrieval latency" would misattribute a third-party API's variance to the
pgvector query. Average and p95 are both reported; an average alone hides the
tail that actually matters.

---

## 4. Rules for reporting numbers

1.  **A model swap invalidates every generation-dependent metric.** Numbers do
    not carry across a model change, and re-measuring is not optional. This is
    why the Groq migration required a full re-run rather than an assumption of
    continuity.
2.  **Report the denominator the harness actually uses.** Figures of "22/22"
    and "8/8" have circulated for this project. Neither was ever produced by
    the current harness, and neither is arithmetically possible against it —
    the dataset holds 25 questions and 11 boundary cases. A plausible-looking
    number is not evidence.
3.  **Delete numbers whose methodology no longer exists.** When the harness was
    rewritten to call the real pipeline, the previous keyword-matching results
    were removed rather than left in place under a methodology they no longer
    reflected. Stale numbers are worse than missing ones, because missing ones
    are visibly missing.
4.  **Record which model produced a result.** Every report now embeds
    `generation_model` in both the JSON summary and the report table, so a
    result can never be silently attributed to the wrong model.
5.  **Distinguish infrastructure failure from model failure.** The harness
    records a generation error as a faithfulness failure, so a free-tier rate
    limit reads as a bad model. Check `had_error_event` in `latest.json` before
    concluding anything about quality.
6.  **State expectations before running.** Predicting "permission compliance
    should be 25/25 because it is LLM-independent" *before* the run turns a
    surprising result into a signal instead of a rationalisation.

---

## 5. Verifying a provider migration

The migration from OpenAI generation to LangChain/Groq followed this sequence.

**Map the existing flow first.** Where generation happens, what the prompt
template contains, how the evaluation harness connects, and where the
authorization boundary sits were established before any edit. This identified
two problems that changed the scope of the work.

**Check the installed packages rather than the documentation.** Langfuse was
recorded as working. Inspecting the installed SDK showed the code calling a v2
API against a v4 package, with the resulting `AttributeError` caught by a broad
`except`, so no spans were recorded.

**Confirm external facts against the provider.** Model identifiers were checked
against Groq's live catalogue. This distinguished `openai/gpt-oss-120b`
(production) from `qwen/qwen3.6-27b` (preview), and established that Groq
serves no embedding model, which determined that embeddings stay on OpenAI. An
earlier candidate, `llama-3.3-70b-versatile`, had already been retired.

**Define the interface contract before changing the implementation.**
`generate_streaming`'s yielded shape is used by five integration tests and by
the evaluation harness. It was recorded before the rewrite and confirmed
afterwards by running the suite unchanged.

**Cover the parts with no other test.** Streaming accumulation, usage parsing,
and reasoning-token exclusion are tested against constructed chunks, so a
failure identifies one function.

**Confirm observability end to end.** The Langfuse fix was verified by running
the span chain and reading the trace back from the API, confirming it carried
the expected user, role, and nested generation observation.

---

## 6. Known gaps

Stated because a methodology document that lists only strengths is marketing.

*   **No baseline exists yet.** Evaluation is blocked because
    `text-embedding-3-small` returns HTTP 403 for the configured OpenAI
    project. See [EVAL_RESULTS.md](EVAL_RESULTS.md).
*   **The corpus is small** (10 documents). It is sized to make permission
    boundaries unambiguous, not to characterise retrieval quality at scale.
*   **Faithfulness scoring is keyword-based** for non-refusal questions —
    substring presence, not semantic equivalence. It detects gross
    unfaithfulness, not subtle distortion.
*   **HNSW is approximate.** A permitted chunk in a distant graph cluster can
    be missed relative to a sequential scan. Discussed in
    [ARCHITECTURE.md](ARCHITECTURE.md) §7.
*   **One integration test requires network access** to the configured
    PostgreSQL instance and fails without it. It verifies behaviour that a
    mock cannot.
*   **The system depends on two providers.** Generation runs on Groq and
    embeddings on OpenAI, because Groq serves no embedding model.
