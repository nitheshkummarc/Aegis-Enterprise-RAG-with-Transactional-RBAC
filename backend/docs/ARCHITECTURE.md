# Aegis Architecture

Aegis is an enterprise Retrieval-Augmented Generation (RAG) system built with a core thesis: **security must be enforced at the database layer, not the application layer.** 

This document outlines the architectural decisions that enable secure, permission-aware RAG without sacrificing retrieval speed or system reliability.

## 1. Single-Query RBAC Enforcement

The primary vulnerability in many enterprise RAG systems is fetching the top-k vectors first, and applying permission filters in-memory afterwards. This can lead to "empty response" bugs if all top-k documents are restricted, or complex multi-round retrieval loops.

Aegis solves this by enforcing Role-Based Access Control (RBAC) at the database layer, in the same SQL statement as the vector search.

*   **Denormalized Permissions**: The `min_role_level` is stored directly on the `document_chunks` table.
*   **Unified Query**: When a user queries the system, the vector similarity ordering and the permission filter are expressed in a single SQL statement — there is no separate step where the application fetches unfiltered results and then discards the ones a role can't see.
    ```sql
    SELECT text_content 
    FROM document_chunks 
    WHERE min_role_level <= :user_role_level 
    ORDER BY embedding <=> :query_embedding 
    LIMIT 3;
    ```
*   **Why it matters**: The system only ever *retrieves* chunks the user is authorized to see — the WHERE clause is part of the same statement doing the ANN ordering, not a post-filter over already-fetched rows. If a viewer searches for admin-level content, the database returns 0 rows, so the LLM has nothing to leak. See [Verified query plan](#verified-query-plan) below for what the actual execution plan does with this, rather than assuming it from the SQL text alone.

### Verified query plan

The claim above ("the filter and the ANN search are one query") is easy to write and easy to get wrong in practice — whether PostgreSQL's planner actually uses the matching partial index for a *bound parameter* (as opposed to a literal) is a real question, not a given. This was checked with `EXPLAIN (ANALYZE, BUFFERS)` against a live Postgres/pgvector 0.8.2 instance, using a throwaway 15,000-row dataset (5,000 chunks per role tier) inserted inside a transaction that was rolled back afterward — nothing was left in the database.

| Role level queried | Index chosen | Rows in that index |
|---|---|---|
| `<= 0` (viewer) | `idx_document_chunks_hnsw_level0` | 5,000 |
| `<= 1` (manager) | `idx_document_chunks_hnsw_level1` | 10,000 |
| `<= 2` (admin) | `idx_document_chunks_hnsw_level2` | 15,000 |

Each query's plan used an **Index Scan** on exactly the partial index whose predicate matches the bound `:user_role_level` value — confirming the planner re-plans per execution (seeing the actual parameter value) rather than reusing a generic cached plan that couldn't make this choice. A viewer's query never touches the manager- or admin-only index at all.

**A caveat, so this section doesn't overclaim in the other direction**: the raw execution times from that same run (1561ms, 1797ms, then 7ms, in query order) are *not* a real latency comparison — they're a cache-warming artifact. The `Buffers` output makes this explicit:

| Role level | Buffer hits (cached) | Buffer reads (disk) |
|---|---|---|
| `<= 0` (ran 1st) | 70 | 1466 |
| `<= 1` (ran 2nd) | 783 | 914 |
| `<= 2` (ran 3rd) | 1386 | 4 |

The data had just been bulk-inserted in the same transaction, so nothing was in `shared_buffers` yet. Each query's candidate set is a superset of the one before it, so by the third query almost every relevant page was already cached from the first two — hence 4 disk reads instead of ~1,500. This says nothing about whether HNSW partial indexes are fast in general; it only confirms the planner picks the right one. Real latency numbers need a warm cache and a realistic corpus size, not a just-populated table in one transaction.

## 2. HNSW Indexing for Cosine Distance

To support fast similarity search at scale, Aegis utilizes PostgreSQL with the `pgvector` extension.

*   **Operator Match**: The database is configured with HNSW (Hierarchical Navigable Small World) indexes specifically using the `vector_cosine_ops` operator class.
*   **Query Match**: The retrieval SQL query explicitly uses the `<=>` operator (cosine distance) rather than `<->` (L2 distance), ensuring the query path perfectly matches the index path.
*   **Per-role partial indexes**: A single HNSW index over the whole table doesn't natively combine with the `min_role_level` filter — the planner can end up ANN-scanning chunks a role isn't even allowed to see, only to discard them post-filter. Since roles are a fixed 3-tier set, Aegis instead builds one *cumulative partial* HNSW index per level (`WHERE min_role_level <= 0/1/2`): a viewer's query only ever scans public content, a manager's scans public+internal, and admin's covers everything. This keeps ANN scan cost proportional to what the querying role can actually see, not the whole table.
*   **Why it matters**: Cosine distance matches the output geometry of the configured embedding model (`GROQ_EMBEDDING_MODEL`, served over Groq's OpenAI-compatible endpoint), and the per-role partial indexes keep retrieval fast for lower-privilege roles even as the admin-only tier of the corpus grows large.

## 3. Isolated Celery Worker Sessions

Asynchronous document ingestion is handled by Celery to prevent long-running PDF extraction and embedding tasks from blocking the FastAPI event loop.

*   **State Isolation**: The Celery worker module (`worker.py`) instantiates its own isolated SQLAlchemy `create_engine` and `sessionmaker`. 
*   **Why it matters**: It deliberately avoids importing FastAPI's request-scoped `get_db` dependency. Sharing a database connection pool across multiprocessing boundaries is a common anti-pattern that leads to connection pool exhaustion and "no application context" errors under heavy upload load. 

## 4. Table-Aware PDF Extraction

PyMuPDF's plain `page.get_text()` reads a table cell-by-cell, left-to-right and top-to-bottom, as flat prose — a revenue-by-region table becomes an unlabeled run of numbers, with each value detached from its row/column label.

*   **Detection**: Each page is also passed through PyMuPDF's `find_tables()`, and any detected table is additionally rendered as a markdown table appended to that page's text.
*   **Why it matters**: Chunking and embedding now have a coherent, row-labeled version of every detected table to work with, not just the scrambled prose version. Table detection is best-effort and wrapped so a page it misjudges never breaks plain text extraction for that page.

## 5. Generation Layer: LangChain over Groq

Generation runs through LangChain's `ChatGroq`, selected by the `GROQ_MODEL` setting and resolved once per process. The layer is deliberately thin — it receives a finished prompt string and returns text.

*   **LangChain wraps generation only, never retrieval.** The idiomatic LangChain RAG pattern is `create_retrieval_chain(retriever, doc_chain)` over a `VectorStore.as_retriever(search_kwargs={"filter": ...})`. Aegis does not use it. That pattern would move the role filter out of the SQL `WHERE` clause and into a framework kwarg — authorization enforced by library configuration rather than by the database. Retrieval stays hand-written SQL (§1); LangChain is handed the result.
*   **The generation layer is authorization-blind by construction.** `generate_streaming()` takes a `str` and yields dicts. It holds no database session, no `User`, no role, and no retriever. Every access decision has already been made before the prompt string exists, which is what keeps the boundary in §1 the *only* boundary.
*   **The prompt is not a `ChatPromptTemplate`.** `build_prompt()` substitutes `{context}` and `{question}` in a single regex pass, specifically so a retrieved chunk containing the literal text `{question}` cannot be overwritten by the live question, and so user input containing braces cannot raise or leak variable names. `ChatPromptTemplate.from_template()` re-parses `{...}` placeholders and would reintroduce exactly that bug, so the rendered string is passed through untouched.
*   **Sent as a single user message.** The strict instructions are delivered as a `HumanMessage`, matching the original implementation's framing. Promoting them to a `SystemMessage` would be a behavior change, not a cleanup — it alters instruction-following and would invalidate any previously measured refusal rate.
*   **Reasoning tokens are suppressed.** `openai/gpt-oss-120b` is a reasoning model and will stream its reasoning trace alongside the answer. The client sets `reasoning_format="hidden"`, and the accumulation loop reads `chunk.text` rather than `chunk.content` so structured reasoning blocks are excluded even if the output format changes. Leaked reasoning text would enter the SSE stream and corrupt the harness's exact refusal-string check (see [METHODOLOGY.md](METHODOLOGY.md)).

### The SSE event contract

`generate_streaming()` yields a fixed shape that both the streaming route and the evaluation harness depend on:

```python
{"type": "token", "text": "..."}                    # zero or more
{"type": "done",  "full_response": str,
                  "usage": {"prompt_tokens", "completion_tokens", "total_tokens"},
                  "model": str}                     # exactly one, always last
```

Groq reports token usage only on the final streamed chunk, and sometimes omits it entirely, so `usage` degrades to `{}` rather than failing — an absent counter is not a generation failure. The `done` event is what carries the `sources` array to the frontend, so it is emitted even for an empty stream.

## 6. Langfuse Observability

Aegis integrates Langfuse to monitor the RAG pipeline's behavior in production. The integration targets the **v4 SDK**, which is OpenTelemetry-based.

*   **Nested Spans**: `/query` opens a root `rag-query` observation carrying the user's email and role, with `1. Permission-Filtered Retrieval` (a `RETRIEVER` observation) and `2. LLM Generation` beneath it. The generation span is entered as the *current* OTEL context, so Langfuse's LangChain callback nests its own `GENERATION` observation inside it — reporting model, prompt, completion and token usage without hand-written instrumentation.
*   **Retrieval is instrumented by hand; generation is not.** A raw pgvector query is not a LangChain operation and no callback can observe it, so its span is created explicitly. It is also the span that documents the authorization boundary, recording the role and the resolved numeric role level used in the `WHERE` clause.
*   **The root span outlives the request handler.** The SSE body is produced by a generator that runs *after* the handler returns, potentially on a different worker thread. The root span is therefore created with the non-context-manager API and ended in the generator's `finally` block; holding an OpenTelemetry context open across that boundary risks detaching it from the wrong thread.
*   **No per-request flush.** The v4 client batches on a background interval and flushes through an `atexit` hook. A blocking flush per request would stall the response for no benefit.
*   **Why it matters**: When auditing a permission denial, an administrator can inspect the trace to prove the database returned zero rows during the retrieval span, confirming the LLM was never exposed to the restricted text.

### A note on how this section used to be wrong

An earlier version of this document described these spans as working. They were not. The route called `langfuse.trace(...)` — an API removed in Langfuse v3 — against an installed v4 SDK. The resulting `AttributeError` was caught by a bare `except Exception` that logged a warning and disabled tracing, so **every span in the query path was silently skipped**, and the only symptom was an empty dashboard.

Two things changed as a result. The client is now validated against the v4 API surface at construction and raises `ConfigurationError` if it does not match, so the next SDK break is a startup failure rather than months of missing data. And the dependency floor moved from `langfuse>=2.0.0` — which resolved happily to a v4 this code could not use — to `langfuse>=3.0.0`. The general lesson is recorded in [ENGINEERING_DECISIONS.md](ENGINEERING_DECISIONS.md): a `try/except` around optional setup converts a loud failure into a silent one, and optional features are precisely the ones nobody notices are missing.

## 7. Known Trade-off: HNSW Approximate Recall vs. Exact Search
Aegis uses the HNSW (Hierarchical Navigable Small World) index for sub-millisecond vector retrieval. HNSW is an Approximate Nearest Neighbor (ANN) algorithm. In edge cases where a permitted chunk is located in a distant graph cluster, HNSW might occasionally miss it compared to a brute-force sequential scan.
- **Mitigation:** For this project's scale (<10k chunks), HNSW provides >99% recall with a fraction of the latency. `ivfflat` would *not* fix this if 100% exact recall were a strict compliance requirement — it's also an approximate algorithm; its recall depends on the `probes` parameter and only approaches 100% as `probes` approaches "every list," which degenerates into a full scan anyway. The only way to guarantee exact recall is to drop the ANN index for that query and run a sequential scan, accepting the latency cost directly rather than trading it for a different approximation.

---

## Related documents

*   [METHODOLOGY.md](METHODOLOGY.md) — how the system is built, and how each claim in this document is verified rather than asserted.
*   [ENGINEERING_DECISIONS.md](ENGINEERING_DECISIONS.md) — the decisions behind this architecture, the alternatives rejected, and what each choice costs.
*   [EVAL_RESULTS.md](EVAL_RESULTS.md) — measured evaluation output.
*   [DEMO_SCRIPT.md](DEMO_SCRIPT.md) — a walkthrough demonstrating the RBAC boundary end to end.

