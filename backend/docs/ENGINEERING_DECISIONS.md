# Aegis Engineering Decisions & Trade-offs

Each entry records a decision, the alternatives considered and rejected, and
the cost the decision carries.

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

## ED-3 · Generation on LangChain and Groq

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
*   Groq's catalogue changes regularly. `llama-3.3-70b-versatile` was retired
    before this work began, so `GROQ_MODEL` should be re-checked against the
    live catalogue rather than assumed valid.
*   Groq serves no embedding model, so embeddings remain on OpenAI and the
    system depends on two providers (ED-14).

---

## ED-4 · LangChain wraps generation only — never retrieval

**Decision.** No `create_retrieval_chain`, no
`VectorStore.as_retriever(search_kwargs={"filter": ...})`. LangChain receives
a finished prompt string and returns text.

**Rationale.** This preserves ED-1. The standard LangChain RAG pattern
expresses the role filter as a retriever argument, which moves the
authorization boundary from the database into framework configuration, where a
refactor, a changed default, or a library upgrade could drop it.

**Consequence.** `generate_streaming()` holds no database session, user, role,
or retriever, so it cannot make an authorization decision.

**Cost.** LangChain's retrieval features (chain composition, retriever
middleware, reranking) are unavailable, and equivalent functionality would have
to be written directly.

---

## ED-5 · No OpenAI generation fallback branch

**Decision.** The OpenAI generation path was removed rather than kept behind a
provider toggle. The `openai` package remains, for embeddings.

**Rejected — a `GENERATION_PROVIDER` switch** offering an apples-to-apples
comparison against `gpt-4o-mini`.

**Rationale.** An unused branch is not exercised or maintained. It would add
`langchain-openai` as a dependency and double the configuration surface, and no
`gpt-4o-mini` baseline was ever measured for it to compare against (ED-9).

**Cost.** Adding an OpenAI generation comparison later requires building and
testing that path separately.

---

## ED-6 · `build_prompt()` stays a regex substitution, not a `ChatPromptTemplate`

**Decision.** The prompt template keeps its single-pass regex substitution for
`{context}` and `{question}`.

**Rationale.** `str.format()` raises or exposes variable names when user input
contains braces. Two chained `.replace()` calls introduce a different problem:
a retrieved chunk containing the literal text `{question}` is overwritten by the
live question on the second pass, replacing document content with user input.
`ChatPromptTemplate.from_template()` re-parses `{...}` placeholders and
reintroduces the same class of problem, so the LangChain migration did not
extend to the prompt.

**Cost.** The prompt is a plain string, so LangChain's prompt tooling —
partials, composition, prompt-hub versioning, automatic input logging — is
unavailable. Pinned by `tests/unit/test_prompt_template.py`.

---

## ED-7 · Hide reasoning tokens; read `.text`, not `.content`

**Decision.** `reasoning_format="hidden"`, and the streaming loop reads
`chunk.text`.

**Rationale.** `openai/gpt-oss-120b` streams its reasoning trace alongside the
answer. Reasoning text entering the SSE stream is accumulated into
`full_response` and breaks the harness's exact refusal-string check, so a model
that refused correctly can be scored as failing. `.text` returns the textual
payload under both LangChain content formats and excludes non-text blocks.

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

**Rationale.** A broad `except Exception` around optional Langfuse setup
converted an `AttributeError` into a log line, and tracing was disabled with no
visible symptom. Optional components need explicit failure handling for this
reason.

The streaming path applies the same rule: `ConfigurationError` is re-raised
rather than reported as a generation failure, because a missing API key is not
a transient fault.

**Cost.** A misconfigured deployment fails rather than degrading. An unset
`GROQ_API_KEY` takes the query path down instead of returning a handled
error.

---

## ED-9 · Delete numbers whose methodology no longer exists

**Decision.** When the eval harness was rewritten to call the real pipeline,
the previous keyword-matching results were deleted rather than carried forward.
`EVAL_RESULTS.md` states that no baseline exists.

**Rationale.** A figure retained past its methodology cannot be reproduced or
interpreted. Figures of 22/22 and 8/8 circulated for this project despite never
having been produced by the current harness, which reports out of 25 questions
and 11 boundary cases.

**Cost.** The project has no headline metrics until the evaluation runs.

---

## ED-10 · A shared observability module rather than duplicated setup

**Decision.** Langfuse client resolution and LangChain callback creation live
in `app/core/observability.py`, used by both the route and the generation
layer.

**Rationale.** Both layers need the same client, settings, and failure
handling. `routes.py` imports `generate.py`, so shared logic placed in either
would create a circular import. A single module gives one place to resolve
tracing configuration.

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

**Rationale.** Each branch in an authorization-sensitive path must be audited.
A linear pipeline has one route from question to answer.

**Cost.** No query rewriting, multi-hop retrieval, or self-correction. Questions
requiring those are answered less well.

---

## ED-14 · Embeddings stay on OpenAI

**Decision.** Text generation runs on Groq; embeddings run on OpenAI's
`text-embedding-3-small`.

**Rejected — moving embeddings to Groq for a single provider.** Groq serves no
embedding model. Its live catalogue for this account lists 14 models covering
chat, speech, and safety classification, with no embedding model among them;
`nomic-embed-text-v1_5` returns HTTP 404. The `/openai/v1/embeddings` path does
respond (401 rather than 404 without credentials), and the Groq SDK exposes an
embeddings method, but no model is served behind it.

**Rejected — local embeddings** via `fastembed` or `sentence-transformers`.
This would remove the second provider and the second key, at the cost of a
model download, CPU time during ingestion, and an additional dependency. It
remains a viable alternative if the OpenAI dependency becomes inconvenient.

**Cost.**
*   Two providers and two API keys.
*   Embedding model access is granted per OpenAI project. `text-embedding-3-small`
    returns HTTP 403 (`project does not have access to model`) until enabled,
    which is a project setting rather than a property of the key.
*   The 1536-dimension output is fixed in the pgvector column and the HNSW
    indexes; changing embedding model requires a schema change and a re-index.

---

## ED-15 · Model identifiers come from the environment only

**Decision.** `GROQ_MODEL`, `EMBEDDING_MODEL`, and `EMBEDDING_DIMENSIONS` have
no defaults in code. An unset value raises rather than falling back.

**Rationale.** Provider catalogues change, and a stale default would run a
model that was not chosen while appearing to work. Requiring the value makes
the running model explicit, which matters when a result is attributed to a
model. CI supplies the three variables directly, as it has no `.env` file.

**Cost.** A new environment must set three variables before the application
starts. `EMBEDDING_DIMENSIONS` must be kept consistent with the deployed schema.

---

## Open questions

*   **Default model.** `openai/gpt-oss-120b` is a production model on Groq;
    `qwen/qwen3.6-27b` is preview, documented as suitable for evaluation only
    and subject to withdrawal, and is priced higher. Both answer from context
    and emit the exact refusal string in direct testing. The decision awaits
    measured results from the evaluation harness.
*   **Embedding provider.** Local embeddings would remove the second provider
    and key (ED-14). Not pursued while OpenAI access is available.
*   **Orthogonal roles.** The integer `min_role_level` model cannot express
    non-hierarchical clearances (ED-1). Whether that matters depends on the
    policy a deployment needs.
*   **Clearance changes after ingestion.** Re-stamping every chunk of a
    reclassified document is understood but not implemented.
