# Aegis Engineering Decisions & Trade-offs

Every entry records a decision, the alternatives that were rejected, and —
most importantly — **what the decision costs**. A trade-off with no stated cost
is a sales pitch, not an engineering record.

[ARCHITECTURE.md](ARCHITECTURE.md) describes the resulting system.
[METHODOLOGY.md](METHODOLOGY.md) describes how these decisions are validated.

---

## ED-1 · Enforce RBAC in SQL, not in application code

**Decision.** Permission filtering lives in the same SQL statement as the
vector search: `WHERE dc.min_role_level <= :user_role_level`, with
`min_role_level` denormalized onto `document_chunks`.

**Rejected — post-filtering in Python.** Fetch top-k, then discard what the
role cannot see. This is the common pattern and it fails in two directions at
once: if all k results are restricted the user gets an empty answer despite
permitted content existing, and every code path that forgets the filter is a
silent leak. It makes authorization a property of application discipline.

**Rejected — a dedicated vector database** (Pinecone, Qdrant) with metadata
filters. This splits permissions across two systems that must be kept in sync,
and makes the authorization boundary a function of correct replication.

**Cost.**
*   Denormalization means a document's clearance change must be propagated to
    every one of its chunks. Reads are made cheap at the cost of that write.
*   It couples the system to PostgreSQL + pgvector. Purpose-built vector
    databases scale further on pure ANN performance.
*   `min_role_level` assumes a **totally ordered** clearance model. Roles that
    are genuinely orthogonal — "Finance" and "Engineering" as peers rather
    than as levels — do not fit an integer comparison and would require a real
    change here, not a bigger number.

---

## ED-2 · Cumulative partial HNSW indexes, one per role level

**Decision.** Three partial HNSW indexes (`WHERE min_role_level <= 0/1/2`)
instead of one index over the whole table.

**Rationale.** A single HNSW index does not natively combine with the role
predicate; the planner can ANN-scan chunks the role may not see and discard
them afterwards. Partial indexes keep scan cost proportional to what the role
can actually access. Verified with `EXPLAIN (ANALYZE, BUFFERS)` — see
[ARCHITECTURE.md](ARCHITECTURE.md#verified-query-plan).

**Cost.**
*   Storage is multiplied: an admin-visible chunk is indexed in all three.
*   Writes maintain up to three indexes.
*   **It only works because the role set is small and fixed.** At a dozen
    roles this approach collapses, and the decision would have to be revisited
    rather than scaled.

---

## ED-3 · Migrate generation to LangChain + Groq

**Decision.** Generation goes through `langchain-groq`'s `ChatGroq`, selected
by `GROQ_MODEL`.

**Rationale.** The model becomes a configuration value rather than a hardcoded
SDK call, so evaluating a candidate is a restart rather than a code change.
The retrieve→generate boundary also becomes explicit.

**Cost.**
*   A dependency layer between the application and the provider API, which is
    a new source of version churn.
*   `langchain-groq` silently coerces `temperature=0.0` to `1e-08` because Groq
    rejects exact zero — a small illustration of the abstraction not being free.
*   Groq's free-tier catalog turns over roughly monthly. This project was
    already hit once: `llama-3.3-70b-versatile` was retired before
    implementation began. `GROQ_MODEL` is a value to re-verify, not to trust.

---

## ED-4 · LangChain wraps generation only — never retrieval

**Decision.** No `create_retrieval_chain`, no
`VectorStore.as_retriever(search_kwargs={"filter": ...})`. LangChain receives
a finished prompt string and returns text.

**Rationale.** This is the decision that protects ED-1. The idiomatic LangChain
RAG pattern would express the role filter as a retriever kwarg — moving the
authorization boundary out of the database and into framework configuration.
The security thesis of this project is precisely that this must not happen. A
filter in a `search_kwargs` dict is one refactor, one default, or one library
upgrade away from not being applied.

**Consequence, deliberately accepted.** `generate_streaming()` holds no
database session, no `User`, no role and no retriever. It *cannot* make an
authorization decision, which is the point.

**Cost.** Aegis forgoes LangChain's retrieval ecosystem — chain composition,
retriever middleware, built-in reranking — and hand-writes what it needs. That
is a real loss of leverage, accepted knowingly.

---

## ED-5 · No OpenAI generation fallback branch

**Decision.** The OpenAI generation path was deleted outright rather than kept
behind a provider toggle. The `openai` SDK remains for embeddings only.

**Rejected — a `GENERATION_PROVIDER` switch** offering an apples-to-apples
comparison against `gpt-4o-mini`.

**Rationale.** A branch nobody exercises is a branch nobody maintains. It would
have carried `langchain-openai` as a dependency, doubled the configuration
surface, and — since no baseline for `gpt-4o-mini` had ever actually been
measured (see ED-9) — bought a comparison against a number that does not exist.

**Cost.** Comparing against OpenAI later means building and testing that path
as its own piece of work. That is the correct place for the cost: paid when
the comparison is genuinely wanted, not carried permanently on the chance that
it might be.

---

## ED-6 · `build_prompt()` stays a regex substitution, not a `ChatPromptTemplate`

**Decision.** The prompt template keeps its single-pass regex substitution for
`{context}` and `{question}`.

**Rationale.** The function exists to defeat a specific bug. `str.format()`
raises or leaks variable names when user input contains braces. Two chained
`.replace()` calls are worse: a retrieved chunk containing the literal text
`{question}` gets overwritten with the live question on the second pass, so
document content is silently rewritten with user input.
`ChatPromptTemplate.from_template()` re-parses `{...}` placeholders and
reintroduces exactly this class of bug. The migration to LangChain was
therefore explicitly *not* extended to the prompt.

**Cost.** The prompt is a plain string, so LangChain's prompt tooling —
partials, composition, prompt-hub versioning, automatic input logging — is
unavailable. Pinned by `tests/unit/test_prompt_template.py`.

---

## ED-7 · Hide reasoning tokens; read `.text`, not `.content`

**Decision.** `reasoning_format="hidden"`, and the streaming loop reads
`chunk.text`.

**Rationale.** `openai/gpt-oss-120b` is a reasoning model that streams its
reasoning trace alongside the answer. Reasoning text entering the SSE stream is
not cosmetic: it is accumulated into `full_response` and corrupts the harness's
exact refusal-string check, so a correctly-refusing model can score as a
failure. `.text` extracts the textual payload under both LangChain content
formats and excludes non-text blocks, so the guard holds even if
`LC_OUTPUT_VERSION` changes the shape of `content`.

**Cost.** The reasoning trace is genuinely useful for debugging refusals and is
discarded. Surfacing it would require a separate channel, not the token stream.

---

## ED-8 · Errors: one policy, three tiers

**Decision.** A single failure policy across the generation and observability
surface.

| Tier | Example | Behaviour |
|---|---|---|
| Misconfiguration | `GROQ_API_KEY` unset, Langfuse SDK API mismatch | Raises `ConfigurationError`. Never caught. |
| Expected absence | Langfuse keys not set; Groq omits usage metadata | Precondition check returning `None` / `{}`. No `try`/`except` at all. |
| Unexpected runtime fault | Exporter failure, auth rejection | Degrades through one logged helper with consistent fields. |

**Rationale.** This policy is a direct response to a real incident in this
repository, not a style preference. A bare `except Exception` around optional
Langfuse setup converted a hard `AttributeError` into a warning line, and
observability was silently dead for months. **Optional features are precisely
the ones whose absence nobody notices**, so they need *louder* failure
handling than mandatory ones, not quieter.

The corollary is enforced in the streaming path: `ConfigurationError` is
re-raised rather than folded into the generic "Generation failed. Please try
again." A missing API key is not a transient fault and must not be dressed as
one.

**Cost.** A misconfigured deployment fails hard instead of degrading. That is
intended, and it does mean an unset `GROQ_API_KEY` takes the query path down
rather than serving a friendly error.

---

## ED-9 · Delete numbers whose methodology no longer exists

**Decision.** When the eval harness was rewritten to call the real pipeline,
the previous keyword-matching results were deleted rather than carried forward.
`EVAL_RESULTS.md` states that no baseline exists.

**Rationale.** Stale numbers are worse than missing numbers, because missing
numbers are visibly missing. Figures of "22/22" and "8/8" have circulated for
this project despite never having been produced by the current harness — and
being arithmetically impossible against it, which holds 25 questions and 11
boundary cases. Once a number is written down, its methodology stops
travelling with it.

**Cost.** The project presents with no headline metrics until the runs happen.
Accepted: a documented absence is more defensible than a number nobody can
reproduce.

---

## ED-10 · A shared observability module rather than duplicated setup

**Decision.** Langfuse client resolution and LangChain callback creation live
in `app/core/observability.py`, used by both the route and the generation
layer.

**Rationale.** Both layers need the same client, the same settings and the same
failure policy. `routes.py` imports `generate.py`, so the shared logic cannot
live in either without a circular import or a badly-placed helper. One module
means "is tracing configured?" has exactly one answer and one place to fix.

**Cost.** One more module, and one more indirection between the route and the
SDK.

---

## ED-11 · The root trace span is created without a context manager

**Decision.** The `rag-query` span uses Langfuse v4's non-context-manager API
and is ended in the SSE generator's `finally` block. Only the generation span
uses `start_as_current_observation`.

**Rationale.** The SSE body is produced by a generator that runs *after* the
handler returns, possibly on a different worker thread. An OpenTelemetry
context entered in the handler and exited in the generator risks being detached
from the wrong thread. Confining context attach/detach to the generator's own
thread avoids the problem entirely.

**Cost.** Span lifecycle is manual, so a missing `finally` leaks an unclosed
span. Trace-level attributes must be attached at creation via
`propagate_attributes` rather than updated later.

---

## ED-12 · Celery workers own their database sessions

**Decision.** `worker.py` builds its own `create_engine` and `sessionmaker`
rather than importing FastAPI's request-scoped `get_db`.

**Rationale.** Sharing a connection pool across process boundaries causes pool
exhaustion and context errors under load.

**Cost.** Two engine configurations to keep aligned; a connection-tuning change
must be made in both.

---

## ED-13 · Linear pipeline, no agent orchestration

**Decision.** `embed → permission-filtered search → generate` is a fixed,
deterministic path. Adopting LangChain for generation (ED-3) did **not**
introduce chains, agents, routers or tool calling.

**Rationale.** Every branch in an authorization-sensitive path is a branch that
must be audited. A linear pipeline has exactly one route from question to
answer, which is what makes the guarantee in ED-1 tractable to reason about.

**Cost.** No query rewriting, no multi-hop retrieval, no self-correction. Some
questions genuinely need those and will answer worse here.

---

## Open questions

Things not yet decided, recorded so they are not mistaken for settled.

*   **Default model.** `openai/gpt-oss-120b` is production on Groq;
    `qwen/qwen3.6-27b` is preview, which Groq states is "for evaluation
    purposes only" and may be withdrawn at short notice, and is also several
    times the price. The decision waits on measured refusal compliance from
    both, with the production/preview distinction weighing alongside the score.
*   **Orthogonal roles.** The integer `min_role_level` model cannot express
    non-hierarchical clearances (ED-1). Whether that matters depends on a
    deployment's actual policy shape.
*   **Clearance changes after ingestion.** Re-stamping every chunk of a
    reclassified document is understood but not implemented.
*   **Embedding quality across the provider swap is unmeasured.**
    `nomic-embed-text-v1_5` is a different model from the `text-embedding-3-small`
    it replaced and may retrieve a different top-k for the same query. If
    faithfulness moves, inspect `sources[]` before blaming the chat model.
*   **Groq's embeddings endpoint is undocumented.** It responds (401 rather
    than 404, unlike a nonexistent path), and the SDK exposes it, but it is
    absent from the public API reference — so its stability carries more risk
    than a documented endpoint would.
