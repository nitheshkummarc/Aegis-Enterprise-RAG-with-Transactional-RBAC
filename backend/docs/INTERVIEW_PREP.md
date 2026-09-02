# Aegis — Interview Preparation

A walkthrough of the project, the reasoning behind it, and the questions an
interviewer is likely to ask.

---

## Read this first: what you can and cannot claim

**The evaluation harness has not been run.** There are no measured accuracy
numbers for this project. Do not quote any.

Two figures — "22/22 permission compliance" and "8/8 boundary cases" — have
circulated for this project. Neither was produced by the current harness, and
neither is possible against it: the dataset holds **25 questions, 11 of them
boundary cases**. Quoting them invites a follow-up question you cannot answer,
and the honest version is more impressive anyway:

> "I have an evaluation harness with 25 questions, 11 of them boundary cases
> and 3 adversarial. I haven't run it yet — embeddings are blocked on an
> OpenAI project permission. I deliberately deleted the old numbers, because
> they came from an earlier harness that approximated retrieval with keyword
> matching, and a number whose methodology no longer exists is worse than no
> number."

That answer demonstrates measurement discipline. A fabricated number
demonstrates the opposite.

**What you can state, because it was verified:**

| Claim | Evidence |
|---|---|
| Test suite passes 105/105 | `pytest`, with the database reachable |
| Both Groq models answer from context and emit the exact refusal string | Direct calls against the live API |
| Langfuse tracing works end to end | Trace read back from the API, with nested generation observation |
| The planner selects the matching partial index per role | `EXPLAIN (ANALYZE, BUFFERS)` against live Postgres |
| Groq serves no embedding model | Live catalogue: 14 models, none embeddings |
| PostgreSQL 17.6, pgvector 0.8.2 | Queried directly |

---

## 1. Problem statement

> Enterprise RAG systems concentrate documents of differing sensitivity into a
> single vector index, then rely on prompt instructions or application-layer
> filtering to prevent users retrieving content above their clearance. Both
> mechanisms fail open. Prompt instructions are not enforcement, and
> application-layer filters run *after* unauthorized content has already been
> retrieved into process memory. A single missed code path, a jailbreak, or a
> filter applied to the wrong variable results in confidential content
> reaching the model's context window, and from there the user.
>
> Aegis enforces clearance inside the database query itself. The permission
> predicate and the vector similarity ordering are one SQL statement, so
> content above a user's clearance is never returned to the application. There
> is nothing to filter and nothing to leak.

### The three failure modes being targeted

1. **Prompt-based access control.** "Only answer this if the user is an
   admin." This is a request, not enforcement.
2. **Post-retrieval filtering.** Fetch top-k, then discard what the role
   cannot see. Unauthorized text enters process memory, logs, and traces
   before being dropped. It also produces the *empty-result bug*: if all k
   results are restricted, the user receives nothing even though permitted
   content exists further down the ranking.
3. **Split-system metadata filtering.** Permissions live in the vector
   database, the source of truth lives in the application database, and the
   two drift.

## 2. Objective

Build a RAG system where:

1. The authorization boundary is a single, auditable SQL predicate.
2. Access control costs nothing in retrieval latency — ideally it *improves*
   it, by reducing the search space.
3. Security is measurable independently of model behaviour.
4. The generation model is swappable without touching retrieval.
5. Every claim in the documentation is verified rather than asserted.

---

## 3. Project walkthrough

### The one thing to show first

[`app/retrieval/search.py:15-27`](../app/retrieval/search.py) — the entire
security thesis:

```sql
SELECT dc.id AS chunk_id, dc.text_content, dc.document_id,
       dc.chunk_index, dc.min_role_level, d.title,
       dc.embedding <=> :query_embedding AS distance
FROM document_chunks dc
JOIN documents d ON d.id = dc.document_id
WHERE dc.min_role_level <= :user_role_level   -- authorization
ORDER BY dc.embedding <=> :query_embedding    -- similarity
LIMIT :limit
```

Say this: *"The `WHERE` and the `ORDER BY` are in one statement. There is no
point in the process where an unauthorized chunk exists in memory."*

### Query path

```
POST /retrieval/query                      routes.py:124
  ├─ JWT validated, role extracted         auth/dependencies.py
  ├─ Langfuse root span opened             routes.py:52
  ├─ embed_query(question)                 ingestion/embedder.py:69
  ├─ permission_filtered_search(...)       retrieval/search.py
  │     role → level via ROLE_LEVEL_MAP    db/models.py:44
  ├─ build_prompt(context, question)       retrieval/prompt.py:20
  └─ event_stream()  (SSE)                 routes.py:192
        └─ generate_streaming(prompt)      retrieval/generate.py:105
              └─ ChatGroq.stream()         retrieval/generate.py:47
```

Two details worth volunteering:

- **The role level is never taken from the client.** The JWT carries a role
  *name*; the numeric level is resolved server-side through a fixed map.
  A forged `"role_level": 99` claim is ignored because nothing reads it.
- **`generate_streaming` has no database session, user, role, or retriever.**
  It takes a string and returns text. It is structurally incapable of making
  an access decision.

### Ingestion path

```
POST /documents/upload-url  → presigned Supabase URL (bytes bypass the API)
   ↓  client uploads directly to storage
Celery task                                  ingestion/worker.py
   0. Idempotency check — skip if chunks exist
   1. Download PDF to temp file
   2. PyMuPDF extraction, tables rendered as markdown
   3. Chunk: 500 chars, 50 overlap
   4. Embed (retry on 429 only, exponential backoff)
   5. Batch insert chunks + status flip — ONE transaction
   6. Delete the raw PDF from storage
```

`min_role_level` is stamped onto every chunk from its parent document at
ingestion. That denormalization is what makes the query in §3.1 a single
table access rather than a join-then-filter.

### Data model

| Role | Level |
|---|---|
| viewer | 0 |
| manager | 1 |
| admin | 2 |

`min_role_level` on both `documents` and `document_chunks`, with a database
`CHECK (min_role_level BETWEEN 0 AND 2)` — enforced even against direct SQL
that bypasses the application.

### Indexing

Three **cumulative partial HNSW indexes** rather than one full-table index:

```sql
CREATE INDEX document_chunks_hnsw_level0 ON document_chunks
  USING hnsw (embedding vector_cosine_ops) WHERE min_role_level <= 0;
-- and the same for <= 1 and <= 2
```

A viewer's query traverses only public vectors. Access control becomes a
performance structure, not just a correctness one.

---

## 4. Interview questions

### Core design

**Q: Why enforce permissions in SQL instead of filtering results in Python?**

Post-filtering retrieves unauthorized content into process memory before
discarding it. That content then exists in variables, logs, traces, and any
crash dump — even though the user never sees it. It also breaks retrieval
quality: if all top-3 results are restricted, the user gets an empty answer
even though permitted content exists at rank 4. Filtering in SQL means the
ranking is computed over the permitted set, so the user gets their best three
*permitted* results.

**Q: Why denormalize `min_role_level` onto chunks instead of joining to
documents?**

A join-then-filter lets the planner evaluate the ANN ordering before the
permission predicate. Denormalizing puts the predicate on the same table as
the vector, so it can be pushed into a partial index. The cost is write
amplification: reclassifying a document requires re-stamping every chunk.
That is a deliberate read-optimized trade.

**Q: Isn't this the same as Postgres row-level security?**

RLS is a legitimate alternative and arguably stronger, since it is enforced by
the database regardless of the query. I chose an explicit predicate for two
reasons: RLS requires setting a session role per request, which interacts
badly with connection pooling (this project uses Supabase's transaction
pooler); and an explicit predicate is visible in `EXPLAIN`, so I can prove
which index served it. A production system with a dedicated connection per
user should seriously consider RLS as defence in depth.

**Q: What happens if someone forges a JWT with a higher role?**

The signature check fails, so the request is rejected at the auth dependency
before retrieval runs. The evaluation harness tests exactly this with two
adversarial cases — a forged `superadmin` role and a null role — and the pass
condition is a `4xx`, which proves no chunk was ever fetched. The algorithm is
also pinned to HS256, so `alg: none` substitution fails.

**Q: Could a user pass their own role level?**

No. The JWT carries a role *name*, and the numeric level is resolved
server-side via `ROLE_LEVEL_MAP`. No code path reads a numeric level from
client input.

### Vector search and pgvector

**Q: Why `<=>` and not `<->`?**

`<=>` is cosine distance and matches the `vector_cosine_ops` operator class
the index is built with. Using `<->` (L2) would make the index unusable for
that query and silently fall back to a sequential scan. Operator and operator
class must match.

**Q: Why HNSW over IVFFlat?**

HNSW gives better recall at a given latency and needs no training step.
IVFFlat requires a populated table to build meaningful lists. Both are
approximate — a point worth making, because people often assume IVFFlat is
exact. Its recall depends on `probes` and only approaches 100% as `probes`
approaches "every list," which degenerates into a full scan.

**Q: How do you know the partial indexes are actually used?**

I checked with `EXPLAIN (ANALYZE, BUFFERS)` against a live instance using a
15,000-row throwaway dataset. Each role level's query used an Index Scan on
exactly the matching partial index. That was worth verifying because the
predicate uses a *bound parameter*, not a literal, and a generic cached plan
could not make that choice — it confirms the planner re-plans per execution.

I also recorded that the execution times from that run (1561ms, 1797ms, 7ms)
are **not** a latency result. The `Buffers` output shows it was cache warming;
each query's candidate set is a superset of the previous one.

**Q: What's the downside of three indexes?**

Storage multiplication — an admin-visible chunk is indexed in all three — and
write cost on insert. It only works because the role set is small and fixed.
At a dozen roles this approach collapses and would need rethinking.

### LangChain and the model layer

**Q: Where did you use LangChain, and why so little of it?**

Only for the generation call: `ChatGroq`, a `HumanMessage`, and `.stream()`.
Roughly 40 lines. I deliberately did not use `create_retrieval_chain` or a
filtered `VectorStore` retriever, because those express the role filter as a
framework argument — `search_kwargs={"filter": ...}`. That moves the
authorization boundary out of the database and into library configuration,
where a refactor, a changed default, or a library upgrade could drop it
silently. The security thesis requires the predicate to stay in SQL.

**Q: Why not use `ChatPromptTemplate`?**

The prompt builder substitutes `{context}` and `{question}` in a single regex
pass. It avoids two bugs: `str.format()` raises or exposes variable names when
user input contains braces, and two chained `.replace()` calls let a retrieved
chunk containing the literal text `{question}` be overwritten by the live
question — document content silently replaced with user input.
`ChatPromptTemplate` re-parses `{...}` placeholders and reintroduces that
class of problem. There is a unit test pinning this behaviour.

**Q: Why Groq?**

Speed and cost for a streaming chat interface, and the model becomes a
configuration value rather than a hardcoded SDK call. `GROQ_MODEL` has no
default in code — an unset value raises — so the running model is always
explicit. That matters when attributing an evaluation result to a model.

**Q: Why are embeddings still on OpenAI?**

Groq serves no embedding model. I verified against the live catalogue: 14
models covering chat, speech, and safety classification, none of them
embeddings. `nomic-embed-text-v1_5` returns 404. The `/v1/embeddings` endpoint
exists — it answers 401 rather than 404 without credentials — but no model is
served behind it. The alternative is local embeddings via `fastembed`, which
would remove the second provider at the cost of CPU time during ingestion.

**Q: What is `reasoning_format="hidden"` for?**

`gpt-oss-120b` is a reasoning model that streams its reasoning trace alongside
the answer. If that reaches the SSE stream it is accumulated into the response
and breaks the harness's exact refusal-string check, so a model that refused
correctly is scored as failing. The streaming loop also reads `chunk.text`
rather than `chunk.content`, which excludes non-text blocks under either
LangChain content format.

### Async and reliability

**Q: Why does the Celery worker build its own database engine?**

Sharing a SQLAlchemy connection pool across process boundaries causes pool
exhaustion and context errors. Celery runs in its own process, so it needs its
own engine and sessionmaker rather than importing FastAPI's request-scoped
dependency.

**Q: How do you avoid double-charging for embeddings?**

An idempotency check at the start of the task: if chunks already exist for
that `document_id`, it returns early. Celery can redeliver a message after a
worker crash, and without that check the redelivery would re-embed the whole
document.

**Q: What's your retry policy?**

Retry only on HTTP 429, with exponential backoff, up to three attempts. A
corrupt PDF is not transient, so extraction failures fail immediately and the
document is marked `failed` rather than retried indefinitely. There is also a
periodic task that marks as failed any document left in `processing` with no
chunks past a timeout.

**Q: What if the worker crashes mid-ingest?**

All chunk inserts and the status update happen in one transaction, so the
document is never left in `ready` with partial chunks. It stays `processing`
and the cleanup task eventually dead-letters it.

### Observability

**Q: What does a trace look like?**

Root `rag-query` span carrying user and role, a retriever span recording the
role level used by the filter, and a generation span reported automatically by
Langfuse's LangChain callback with model, prompt, completion, and token usage.

**Q: Why is retrieval instrumented by hand but generation isn't?**

A raw pgvector query is not a LangChain operation, so no callback can observe
it. Generation is, so the callback reports it. The retrieval span is also the
one that documents the authorization boundary, which is why it records the
resolved role level.

**Q: Tell me about a bug you found.** *(A strong answer — have it ready.)*

Tracing was documented as working and was completely dead. The route called
`langfuse.trace(...)`, an API removed in Langfuse v3, against an installed v4
SDK. The resulting `AttributeError` was caught by a broad `except Exception`
that logged a warning and disabled tracing. The only symptom was an empty
dashboard, and the dependency pin `langfuse>=2.0.0` happily resolved to the v4
release the code could not use.

Three changes came out of it: the client is now validated against the v4 API
at construction and raises if it does not match; the floor moved to
`langfuse>=3.0.0`; and the error policy changed so misconfiguration raises
rather than degrading. The general lesson is that optional features are
exactly the ones whose absence nobody notices, so they need *louder* failure
handling than mandatory ones, not quieter.

I verified the fix by running the span chain and reading the trace back from
the API to confirm it carried the expected user, role, and nested generation
observation — "the code calls the right API" and "the data arrives" are
different claims.

### Evaluation

**Q: How do you know the RBAC actually works?**

Four layers. Unit tests on role-to-level resolution; security tests on the
permission filter; an integration test against real PostgreSQL confirming a
viewer receives zero admin chunks; and the evaluation harness running every
question end to end through the real endpoint with real JWTs.

The integration test is deliberately not mocked. A mocked database confirms
only that the application sends the SQL it was written to send — it cannot
confirm that PostgreSQL, pgvector, and the chosen index honour the predicate.

**Q: What do your two metrics measure?**

Permission compliance is scored from `min_role_level` on a direct call to the
search function, so it is structurally independent of the language model — no
prompt change or model swap can move it. Faithfulness is scored on the model's
actual generated text, reassembled from the SSE stream.

They are separate on purpose. A chunk-level check cannot distinguish "the
model correctly refused" from "the model ignored its instructions and answered
from prior knowledge" — both produce zero retrieved chunks. Only the generated
text separates them.

**Q: What does your evaluation *not* prove?**

Permission compliance says nothing about answer quality — it would read 25/25
for a model returning empty strings. Faithfulness says nothing about security
— a model can be perfectly faithful to context it should never have received.
Neither covers upload-time misclassification: if a document is stamped with
the wrong level at ingestion, every downstream check passes while enforcing
the wrong policy.

### Trade-offs and weaknesses

Have these ready. Volunteering them reads as engineering maturity; being
caught without them does not.

**Q: What are the limitations?**

- **Ordered clearances only.** `min_role_level` is an integer, so genuinely
  orthogonal roles — Finance and Engineering as peers rather than levels — do
  not fit. That needs a different model, not a bigger number.
- **HNSW is approximate.** A permitted chunk in a distant graph cluster can be
  missed relative to a sequential scan. For this corpus size that is an
  acceptable trade; a strict-recall requirement would mean dropping the ANN
  index and accepting the latency.
- **Partial indexes assume a small fixed role set.**
- **Reclassification is not implemented.**
- **Upload-time misclassification is out of scope.**
- **Two providers**, so two keys and two failure domains.
- **No measured evaluation yet.**

**Q: What would you do next?**

Run the evaluation once embeddings are unblocked; add reclassification with
chunk re-stamping; consider RLS as defence in depth; and evaluate local
embeddings to remove the second provider.

**Q: What would you do differently?**

Pin dependencies to a tighter range. `langfuse>=2.0.0` resolving to v4 is what
allowed the API mismatch, and a bare `except` is what hid it. The lesson
generalised into the current error policy: configuration errors raise,
expected absences are precondition checks, and only genuine runtime faults
degrade — through one helper, so there is one place to look.

---

## 5. Rapid-fire facts

| Question | Answer |
|---|---|
| Chunk size / overlap | 500 chars / 50 |
| Roles | viewer 0, manager 1, admin 2 |
| Retrieval limit | top 3 |
| Embedding dims | 1536 (`text-embedding-3-small`) |
| Distance operator | `<=>` cosine, matching `vector_cosine_ops` |
| Indexes | 3 cumulative partial HNSW |
| Rate limits | 5/min auth, 10/min upload, 20/min query |
| JWT | HS256, algorithm pinned |
| Passwords | bcrypt |
| Tests | 105 |
| Dataset | 25 questions, 11 boundary, 3 adversarial |
| Refusal string | `I do not have access to that information.` |

---

## 6. Two-minute pitch

> Aegis is an enterprise RAG system that enforces role-based access control
> inside the database query rather than in application code.
>
> The problem is that most RAG systems put every document into one vector
> index and then rely on prompt instructions or Python-side filtering to keep
> users from seeing content above their clearance. Both fail open. Prompt
> instructions aren't enforcement, and post-filtering means unauthorized text
> has already been retrieved into memory before it's discarded.
>
> Aegis denormalizes a clearance level onto every chunk and puts the
> permission predicate in the same SQL statement as the vector similarity
> ordering. Unauthorized content is never returned to the application at all.
> It also builds one partial HNSW index per clearance level, so a low-privilege
> user's search physically cannot traverse restricted vectors — access control
> becomes a performance optimization rather than a tax. I verified that with
> `EXPLAIN` against a live database rather than assuming it.
>
> The stack is FastAPI, PostgreSQL with pgvector, Celery for async ingestion,
> LangChain with Groq for generation, and Langfuse for tracing. LangChain is
> used deliberately narrowly — generation only. The standard LangChain RAG
> pattern expresses the role filter as a retriever argument, and I didn't want
> the authorization boundary living in framework configuration.
>
> The part I'd most want to talk about is the evaluation design: permission
> compliance is scored from SQL, so it's structurally independent of the
> language model, which means a model swap cannot silently change my security
> number.

---

## Related documents

- [ARCHITECTURE.md](ARCHITECTURE.md) — system design and verified query plan
- [ENGINEERING_DECISIONS.md](ENGINEERING_DECISIONS.md) — decisions, rejected
  alternatives, and costs
- [METHODOLOGY.md](METHODOLOGY.md) — how claims are verified
- [EVAL_RESULTS.md](EVAL_RESULTS.md) — evaluation status
- [DEMO_SCRIPT.md](DEMO_SCRIPT.md) — live walkthrough
