# Aegis Methodology

[ARCHITECTURE.md](ARCHITECTURE.md) describes *what* the system is.
[ENGINEERING_DECISIONS.md](ENGINEERING_DECISIONS.md) describes *why* it is
shaped that way. This document describes **how it is built and how its claims
are checked** — the working practices that decide whether a statement in this
repository is an assertion or a measurement.

The organising principle is simple and is applied throughout: **a security
claim that has not been measured is not a claim, it is a hope.** Most of what
follows is machinery for telling those two apart.

---

## 1. The corpus is synthetic, and deliberately so

Evaluating an RBAC system requires knowing the ground truth of who may see
what. Real documents do not come with that label, and mislabeling even one of
them silently corrupts every permission metric computed from it.

`scripts/generate_synthetic_corpus.py` therefore generates the corpus with
known clearance tiers: 10 documents across viewer, manager and admin levels,
each chunked and embedded through the same `app.ingestion.chunker` and
`app.ingestion.embedder` path a real upload would take. The evaluation is
end-to-end over the real pipeline; only the *authorship* of the documents is
synthetic.

**Cross-contamination checks matter more than volume here.** A corpus where
admin-tier facts also appear in viewer-tier documents cannot detect a
permission leak — the leaked answer would be independently reachable, and
every test would pass for the wrong reason. Distinctive, tier-exclusive facts
are what give the refusal cases their meaning.

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

The integration test is the important one, and it is deliberately not mocked.
A mocked database can only confirm that the application sends the SQL it was
written to send; it cannot confirm that PostgreSQL, pgvector and the chosen
index actually honour the predicate. That is a different claim and needs a
real engine to test.

The same reasoning produced the `EXPLAIN (ANALYZE, BUFFERS)` verification
recorded in [ARCHITECTURE.md](ARCHITECTURE.md#verified-query-plan). "The
filter and the ANN search are one query" is a statement about a *query plan*,
not about SQL text, and whether the planner selects the matching partial index
for a **bound parameter** rather than a literal is a genuine open question. It
was checked against a live instance instead of reasoned about.

That section also demonstrates the second half of the practice: the same
verification produced execution times of 1561ms, 1797ms and 7ms, which look
like a dramatic performance result and are in fact a cache-warming artifact.
The `Buffers` output says so plainly. Reporting the timings as a speedup would
have been the more impressive and less honest choice.

---

## 3. Evaluation methodology

`eval/run_eval.py` runs every question in `eval/golden_dataset.json` through
the real `/retrieval/query` endpoint using real JWTs minted by the backend's
own `create_access_token`. Nothing in the path is mocked: real embedding, real
pgvector search, real Groq generation, real SSE stream.

### Dataset composition

**25 questions**, of which **11 are boundary cases** and **3 are adversarial**.
Those denominators are the ones any honest report uses.

### The two metrics measure different things

This distinction is the core of the methodology, and conflating the two is the
most common way an RBAC evaluation flatters itself.

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

The reason faithfulness is scored on generated text rather than on retrieved
chunks is worth stating explicitly: a chunk-level check cannot distinguish
*"the model correctly refused"* from *"the model ignored its instructions and
answered from parametric knowledge anyway."* Both produce zero retrieved
chunks. Only the generated text separates them.

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

These exist because this project has already been burned by their absence.

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

## 5. How a dependency migration is verified

The migration from a direct OpenAI call to LangChain/Groq followed a sequence
worth recording, because the mapping step is what caught the real problems.

**Map before touching.** The current flow was traced end to end first — where
generation happens, what the prompt template is, how the eval harness hooks in,
and where the authorization boundary sits. That step surfaced two findings that
changed the scope of the work, both of which would have been missed by starting
with the edit.

**Verify the environment's claims, don't inherit them.** Langfuse was described
as "already wired in." Inspecting the installed SDK showed the code calling a
v2 API against a v4 package, with the resulting `AttributeError` swallowed by a
bare `except`. Tracing had been dead for months. The check that found it was
one command against the installed package, not a code review.

**Confirm external facts against the source.** Both target model IDs were
verified against Groq's live catalog before implementation, which is also how
`openai/gpt-oss-120b` (production) and `qwen/qwen3.6-27b` (preview, and
explicitly "for evaluation only") were distinguished — a difference that
belongs in a default-model decision. An earlier candidate for this migration,
`llama-3.3-70b-versatile`, had already been retired from the free tier.

**Establish the contract, then hold it.** `generate_streaming`'s yielded shape
is depended on by five integration tests and by the eval harness. It was
written down explicitly before the rewrite and verified afterwards by running
the suite with **zero test files modified** — the strongest available evidence
that the swap was behaviour-preserving.

**Test the parts that have no other guard.** Streaming accumulation, usage
parsing and reasoning-token exclusion were exercised against hand-built chunks,
so a failure in any of them points at one function rather than at a request
handler.

**Prove the observability, don't assume it.** The Langfuse fix was confirmed by
driving the real span chain and then *fetching the trace back from the API* to
confirm it carried the expected user, role and nested generation observation.
"The code now calls the right API" and "the data arrives" are different claims.

---

## 6. Known gaps

Stated because a methodology document that lists only strengths is marketing.

*   **No baseline exists yet for the Groq generation layer.** The runs are
    blocked on a `GROQ_API_KEY` and on a reachable seeded database. See
    [EVAL_RESULTS.md](EVAL_RESULTS.md).
*   **The corpus is small** (10 documents). It is sized to make permission
    boundaries unambiguous, not to characterise retrieval quality at scale.
*   **Faithfulness scoring is keyword-based** for non-refusal questions —
    substring presence, not semantic equivalence. It detects gross
    unfaithfulness, not subtle distortion.
*   **HNSW is approximate.** A permitted chunk in a distant graph cluster can
    be missed relative to a sequential scan. Discussed in
    [ARCHITECTURE.md](ARCHITECTURE.md) §7.
*   **One integration test requires network reachability** to the configured
    Postgres instance and fails in environments without it. It is a real test
    of a real guarantee, and mocking it away would defeat its purpose.
