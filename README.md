# Aegis

> Most RAG systems retrieve first and check permissions afterwards. Aegis puts the permission check inside the same SQL statement as the vector search, so content above a user's clearance is never returned to the application at all.

---

## The idea

An organisation has documents at different sensitivity levels: a public holiday
policy, an internal roadmap, an unreleased financial forecast. You want one
search box over all of them, and you want the answer to depend on who is asking.

The obvious way to build this is to put every document in one vector index,
retrieve the closest matches to the question, and then remove the ones the user
is not allowed to see before sending the rest to the model. This is what most
tutorials and most framework defaults do.

Two things go wrong.

**The filter runs too late.** By the time you drop the restricted chunks, they
have already been read out of the database, deserialised into your process, and
placed in a variable. They are in memory. If tracing is on, they may be in your
observability backend. If the process crashes between retrieval and filtering,
they are in the crash dump. The data was protected by the fact that a particular
line of Python ran — not by anything structural.

**The filter breaks retrieval quality.** Concretely: a viewer asks about
severance policy. The three closest chunks are all from an admin-only
compensation document, so after filtering the viewer gets nothing — even though
a permitted chunk answering the question sat at rank four. The system reports
"no information" while the information exists and the user is allowed to see it.

Aegis stores a clearance level on every chunk and writes the query so that the
permission predicate and the similarity ordering are evaluated together:

```sql
SELECT dc.text_content, d.title, dc.min_role_level
FROM document_chunks dc
JOIN documents d ON d.id = dc.document_id
WHERE dc.min_role_level <= :user_role_level   -- authorization
ORDER BY dc.embedding <=> :query_embedding    -- similarity
LIMIT :limit
```

The ranking is computed over the permitted set. The viewer gets their best three
*permitted* chunks, and restricted rows are never sent over the wire. There is
no filtering step to forget, and nothing to leak.

The numeric level is resolved server-side from the JWT's role claim through a
fixed map (`app/db/models.py`). A client-supplied level is never read.

---

## Architecture

| # | Stage | Kind | Component |
|---|---|---|---|
| 1 | Upload → presigned URL | Deterministic | `app/documents/service.py` |
| 2 | PDF text + table extraction | Deterministic | `app/ingestion/parser.py` (PyMuPDF) |
| 3 | Chunking (500 chars, 50 overlap) | Deterministic | `app/ingestion/chunker.py` |
| 4 | Embedding | **Model** | `app/ingestion/embedder.py` (OpenAI) |
| 5 | Stamp `min_role_level`, batch insert | Deterministic | `app/ingestion/worker.py` |
| 6 | Authenticate, resolve role → level | Deterministic | `app/auth/` |
| 7 | Embed query | **Model** | `app/ingestion/embedder.py` |
| 8 | **Permission-filtered vector search** | **Deterministic** | `app/retrieval/search.py` |
| 9 | Prompt assembly | Deterministic | `app/retrieval/prompt.py` |
| 10 | Answer generation | **Model** | `app/retrieval/generate.py` (Groq) |
| 11 | SSE streaming to client | Deterministic | `app/retrieval/routes.py` |

### Where model involvement starts and stops

Models are used in exactly three places: embedding at ingest (4), embedding the
query (7), and generating the answer (10).

**Stage 8 — the authorization boundary — is deterministic SQL.** No model, no
framework retriever, no prompt instruction participates in the access decision.

This is enforced structurally rather than by convention. `generate_streaming()`
takes a `str` and yields dicts; it holds no database session, no user, no role,
and no retriever, so it has nothing to make an access decision *with*.

### Why LangChain is used narrowly

LangChain appears only at stage 10: `ChatGroq`, one `HumanMessage`, and
`.stream()`. The following are deliberately not used:

| Not used | Reason |
|---|---|
| `create_retrieval_chain` | Puts retrieval behind a framework abstraction |
| `as_retriever(search_kwargs={"filter": ...})` | Expresses the role filter as a library argument |
| `PGVector` vector store | Would generate its own SQL, replacing the audited query |
| `ChatPromptTemplate` | Re-parses `{...}`; see "What makes this honest" |
| Agents, routers, tool calling | Adds branches to an authorization-sensitive path |

---

## What makes this honest

### Proven by tests that exist in this repo

- **Role → level resolution ignores client input.** `tests/unit/test_search_query_builder.py` (10 tests).
- **The permission filter rejects the cases it should.** `tests/security/test_rbac_enforcement.py` (6 tests), against SQLite.
- **A real PostgreSQL instance returns zero admin chunks to a viewer.** `tests/integration/test_rbac_end_to_end.py` (1 test). This is the only test that exercises real pgvector.
- **Prompt substitution is injection-safe.** `tests/unit/test_prompt_template.py` (8 tests), including that a chunk containing the literal text `{question}` is not overwritten by the live question.
- **The SSE event contract holds**, including that reasoning blocks never enter the token stream. `tests/unit/test_generation_streaming.py` (11 tests).
- **Ingestion is idempotent and retries only on rate limits.** `tests/integration/test_ingestion_worker.py` (11 tests).

### Verified by hand, once, and not re-run automatically

- **The planner selects the matching partial index per role.** Checked with `EXPLAIN (ANALYZE, BUFFERS)` against live PostgreSQL 17.6 / pgvector 0.8.2. See "Results". Nothing re-checks this in CI; an index change could regress it silently.
- **Langfuse tracing produces a populated generation span.** Confirmed by reading a trace back from the Langfuse API. Not covered by any test.
- **Both Groq models emit the exact refusal string.** Confirmed by direct API calls. Not covered by any test.

### Assumed, not proven

- **That `min_role_level` is correct at ingest.** Every downstream guarantee depends on documents being stamped with the right clearance. If a document is misclassified at upload, every test still passes while the wrong policy is enforced. Nothing in this repo validates classification correctness.
- **That HNSW recall is adequate.** HNSW is approximate. A permitted chunk in a distant graph region can be missed relative to a sequential scan. Recall is not measured.
- **That the synthetic corpus resembles real documents.** It is 10 generated documents. Retrieval quality on real enterprise PDFs is unmeasured.

### Untested paths

- **The frontend has 3 tests**, covering the sources dropdown only. Login, chat, and SSE consumption in the browser are untested.
- **Celery retry/backoff timing** is tested via mocks, not against a live broker.
- **Supabase storage operations** are mocked in tests. Presigned upload against real storage is untested.
- **`cleanup_stuck_documents`** has no dedicated test.
- **Concurrency** is untested. No test exercises simultaneous queries from different roles.
- **The 403/429 provider-error paths** in the route are tested with mocked exceptions, not real provider failures.

### What the numbers do not measure

- Permission compliance is scored from `min_role_level` on a direct SQL call. It is **independent of the language model** — which is the point, but it also means it says nothing about answer quality. It would score perfectly for a model that returns empty strings.
- Faithfulness is scored by substring matching against expected keywords, not semantic equivalence. It detects gross unfaithfulness, not subtle distortion.
- Retrieval latency is **database time only**. The embedding round-trip is outside the timer.

---

## Status

Backend test counts from `pytest --collect-only`. **105 backend tests total.**

| Module | Tests | File |
|---|---|---|
| Upload flow | 13 | `tests/integration/test_upload_flow.py` |
| Generation / SSE contract | 11 | `tests/unit/test_generation_streaming.py` |
| Ingestion worker | 11 | `tests/integration/test_ingestion_worker.py` |
| Search query builder | 10 | `tests/unit/test_search_query_builder.py` |
| Chunker | 10 | `tests/unit/test_chunker.py` |
| Auth routes | 9 | `tests/integration/test_auth_routes.py` |
| Prompt template | 8 | `tests/unit/test_prompt_template.py` |
| JWT | 7 | `tests/unit/test_jwt.py` |
| RBAC enforcement (SQLite) | 6 | `tests/security/test_rbac_enforcement.py` |
| Query flow | 6 | `tests/integration/test_query_flow.py` |
| PDF parser | 5 | `tests/unit/test_parser.py` |
| Rate limiter | 5 | `tests/unit/test_limiter.py` |
| Document listing | 3 | `tests/integration/test_document_listing.py` |
| RBAC end-to-end (real Postgres) | 1 | `tests/integration/test_rbac_end_to_end.py` |
| **Frontend** | **3** | `frontend/tests/SourcesDropdown.test.tsx` |

104 of the 105 backend tests run without network access. `test_rbac_end_to_end.py`
connects to the configured PostgreSQL instance and fails with a connection
timeout when it is unreachable.

### Component state

| Component | State |
|---|---|
| Permission-filtered search | Implemented, tested |
| Partial HNSW indexes | Implemented, query plan verified by hand |
| Async ingestion (Celery) | Implemented, tested with mocks |
| Generation (Groq via LangChain) | Implemented, tested via mocks; live calls confirmed by hand |
| Embeddings (OpenAI) | Implemented; **currently returns HTTP 403** — the configured OpenAI project lacks access to `text-embedding-3-small` |
| Langfuse tracing | Implemented, verified by hand, not covered by tests |
| Evaluation harness | Implemented, **never run to completion** |
| Frontend | Implemented, 3 tests |

---

## Results

### Query plan verification

Checked with `EXPLAIN (ANALYZE, BUFFERS)` against live PostgreSQL 17.6 /
pgvector 0.8.2, using a 15,000-row throwaway dataset (5,000 chunks per tier)
inserted in a transaction that was rolled back.

| Role level | Index chosen | Rows in index |
|---|---|---|
| `<= 0` (viewer) | `document_chunks_hnsw_level0` | 5,000 |
| `<= 1` (manager) | `document_chunks_hnsw_level1` | 10,000 |
| `<= 2` (admin) | `document_chunks_hnsw_level2` | 15,000 |

Each query used an Index Scan on the partial index matching the bound
parameter, confirming the planner re-plans per execution rather than reusing a
generic plan.

**What this measures:** index selection, on one machine, on a synthetic dataset,
once. **What it does not measure:** recall, latency, or behaviour at a realistic
corpus size or under concurrency.

**The timings from that run are not a performance result.** Execution times were
1561 ms, 1797 ms, then 7 ms in query order. That looks like the restrictive
index is 200× faster. It is not — it is cache warming, as the buffer counts show:

| Role level | Buffer hits | Disk reads |
|---|---|---|
| `<= 0` (ran 1st) | 70 | 1466 |
| `<= 1` (ran 2nd) | 783 | 914 |
| `<= 2` (ran 3rd) | 1386 | 4 |

The data had just been bulk-inserted, so nothing was cached. Each query's
candidate set is a superset of the previous one, so by the third query almost
every page was already resident. Reported as a speedup, this would be false.

### Provider capability check

Groq's live model catalogue for the configured account returns 14 models,
covering chat, speech, and safety classification. **None is an embedding model.**
`nomic-embed-text-v1_5` returns HTTP 404. The `/openai/v1/embeddings` endpoint
exists — it answers 401 rather than 404 without credentials — but no model is
served behind it. This is why embeddings run on OpenAI.

### Evaluation results

**None. The harness has never been run to completion.**

It is blocked: `text-embedding-3-small` returns HTTP 403 (`project does not have
access to model`) for the configured OpenAI project, and every question requires
a query embedding.

The dataset is **25 questions — 11 boundary cases and 3 adversarial**, so a
complete run reports out of 25 and 11.

- Permission compliance: [NEEDS: run `python -m eval.run_eval`]
- Boundary cases: [NEEDS: run `python -m eval.run_eval`]
- Faithfulness: [NEEDS: run `python -m eval.run_eval`]
- Retrieval latency (avg, p95): [NEEDS: run `python -m eval.run_eval`]
- Comparison across `openai/gpt-oss-120b` vs `qwen/qwen3.6-27b`: [NEEDS: two runs, one per `GROQ_MODEL`]
- Baseline comparison against a post-filtering implementation: [NEEDS: no baseline implementation exists in this repo]

Two figures — 22/22 permission compliance and 8/8 boundary cases — have
circulated for this project. **Neither was produced by the current harness, and
neither is arithmetically possible against it**, since the dataset holds 25
questions and 11 boundary cases. Earlier figures committed to this repo
(25/25, 11/11, faithfulness 1.00, commit `c3cf9be`) came from a prior harness
that approximated retrieval with keyword matching rather than calling the
pipeline; they were deleted rather than carried forward.

**Expected result, stated before the run:** permission compliance should read
25/25 for both models, because it is scored from SQL and does not depend on the
model. A different figure indicates a regression in the authorization boundary,
not a model difference.

---

## Running

### Prerequisites

- Docker and Docker Compose
- A Groq API key (generation)
- An OpenAI API key with `text-embedding-3-small` enabled on the project (embeddings)

> Embedding access is granted per OpenAI project under **Settings → Limits →
> Model access**, and requires a non-zero credit balance. A key alone is not
> sufficient; this is the current blocker described under "Results".

### Setup

```bash
git clone https://github.com/nitheshkummarc/Aegis-Enterprise-RAG-with-Transactional-RBAC.git
cd Aegis-Enterprise-RAG-with-Transactional-RBAC
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local
# edit both files with your keys
```

### Backend stack

```bash
docker-compose up -d --build
```

Starts PostgreSQL (pgvector), Redis, the FastAPI backend on `:8000`, and the
Celery worker. Migrations run on backend startup.

### Frontend (not containerised)

```bash
cd frontend
npm install
npm run dev
```

### Confirm embedding width matches the schema

```bash
cd backend
python -m scripts.verify_embedding_dimensions
```

Compares the model's actual output width against `EMBEDDING_DIMENSIONS`. If they
differ it prints the files to change. Run this before seeding.

### Seed

```bash
cd backend
python -m scripts.seed_users
python -m scripts.generate_synthetic_corpus
```

### Tests

```bash
cd backend
pytest                                    # 105 tests; 1 requires a reachable database

cd frontend
npm test                                  # 3 tests
```

### Evaluation

```bash
cd backend
GROQ_MODEL=openai/gpt-oss-120b python -m eval.run_eval
cp eval/results/latest.json eval/results/groq-gpt-oss-120b.json

GROQ_MODEL=qwen/qwen3.6-27b   python -m eval.run_eval
cp eval/results/latest.json eval/results/groq-qwen3.6-27b.json
```

`run_eval.py` overwrites `docs/EVAL_RESULTS.md` and `eval/results/latest.json`
on every run, so copy each result aside before the next model.

### Seeded users

| Role | Email | Password |
|---|---|---|
| Admin | `admin@clearancerag.test` | `admin123` |
| Manager | `manager@clearancerag.test` | `manager123` |
| Viewer | `viewer@clearancerag.test` | `viewer123` |

---

## Layout

```text
backend/
├── app/
│   ├── auth/          JWT issue/verify, password hashing, role dependencies
│   ├── core/          Exceptions, rate limiter, Langfuse client wiring
│   ├── db/            SQLAlchemy models, Alembic migrations, schema reference
│   ├── documents/     Presigned upload URLs, document listing
│   ├── ingestion/     Celery worker, PDF parser, chunker, embedder
│   └── retrieval/     Permission-filtered search, prompt, generation, SSE route
├── docs/              Architecture, methodology, decisions, evaluation status
├── eval/              Golden dataset and evaluation harness
├── scripts/           User seeding, synthetic corpus, embedding-width check
└── tests/             unit / integration / security
frontend/              Next.js App Router, Auth.js, SSE chat UI
.github/workflows/     CI: backend tests against real Postgres and Redis
docker-compose.yml     Postgres (pgvector), Redis, backend, Celery worker
```

---

## Configuration

All backend variables are read from `backend/.env` via pydantic-settings.

| Variable | Default | Purpose |
|---|---|---|
| `ENVIRONMENT` | `development` | Set to `production` to enable secret validation |
| `DATABASE_URL` | local postgres URL | PostgreSQL connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Celery broker and rate-limit storage |
| `GROQ_API_KEY` | *(empty)* | Groq credential for generation |
| `GROQ_MODEL` | *(empty — required)* | Chat model id. No default, so the running model is explicit |
| `GROQ_API_BASE` | `https://api.groq.com/openai/v1` | Groq OpenAI-compatible endpoint |
| `OPENAI_API_KEY` | *(empty)* | OpenAI credential for embeddings |
| `EMBEDDING_MODEL` | *(empty — required)* | Embedding model id |
| `EMBEDDING_DIMENSIONS` | `0` (required) | Vector width; must equal the model output and the pgvector column |
| `JWT_SECRET_KEY` | `change-me-to-a-random-secret` | HMAC signing key; must be ≥32 chars in production |
| `JWT_ALGORITHM` | `HS256` | Pinned; `alg` substitution is rejected |
| `JWT_EXPIRE_MINUTES` | `60` | Access token lifetime |
| `BACKEND_URL` | `http://localhost:8000` | Backend base URL |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowed origins |
| `TRUSTED_PROXY_IPS` | *(empty)* | Only these IPs may set `X-Forwarded-For` for rate limiting |
| `STUCK_DOCUMENT_TIMEOUT_MINUTES` | `60` | Age at which a stalled document is marked failed |
| `LANGFUSE_PUBLIC_KEY` | *(empty)* | Tracing; absent disables tracing without error |
| `LANGFUSE_SECRET_KEY` | *(empty)* | Tracing |
| `LANGFUSE_HOST` | `https://cloud.langfuse.com` | Langfuse endpoint |
| `SUPABASE_URL` | *(empty)* | Object storage for uploaded PDFs |
| `SUPABASE_SERVICE_KEY` | *(empty)* | Storage credential |
| `NEXTAUTH_SECRET` | *(empty)* | Declared but unused by the backend; the frontend reads its own |
| `NEXTAUTH_URL` | `http://localhost:3000` | Declared but unused by the backend |

`GROQ_MODEL`, `EMBEDDING_MODEL`, and `EMBEDDING_DIMENSIONS` raise on access if
unset. CI supplies them explicitly since it has no `.env` file.

---

## Deliberately out of scope

**Orthogonal roles.** `min_role_level` is an integer, so clearances must be
totally ordered. Roles that are peers rather than levels — Finance and
Engineering — do not fit. Supporting them means a different data model, not a
larger integer. Chosen because a totally ordered model is what makes the single
comparison in the query, and therefore the partial indexes, possible.

**Postgres row-level security.** RLS would enforce the predicate regardless of
the query, which is stronger. It requires setting a session role per request,
which interacts badly with the transaction pooler this project uses, and it does
not appear in `EXPLAIN` in a way that lets you prove which index served a query.
An explicit predicate was chosen for poolability and auditability. RLS remains
the right addition for defence in depth.

**A dedicated vector database.** Pinecone or Qdrant would scale further on pure
ANN performance. Both would split permissions across two systems that must stay
in sync, which is the failure mode this project exists to remove.

**Agents, query rewriting, multi-hop retrieval, reranking.** The pipeline is one
fixed path from question to answer. Every branch in an authorization-sensitive
path is a branch that has to be audited. The cost is that questions genuinely
needing decomposition are answered less well.

**An OpenAI generation fallback.** Removed rather than kept behind a toggle. An
unexercised branch is not maintained, and no `gpt-4o-mini` baseline was ever
measured for it to compare against.

**Reclassification.** Changing a document's clearance after ingest would require
re-stamping every chunk. Understood, not implemented.

**Document classification.** Aegis enforces the clearance it is given. Deciding
what clearance a document deserves is a separate problem and is not addressed.

---

## Documentation

| Document | Contents |
|---|---|
| [ARCHITECTURE.md](backend/docs/ARCHITECTURE.md) | System design, query plan verification, span structure |
| [ENGINEERING_DECISIONS.md](backend/docs/ENGINEERING_DECISIONS.md) | 15 decisions with rejected alternatives and costs |
| [METHODOLOGY.md](backend/docs/METHODOLOGY.md) | How claims are verified; rules for reporting numbers |
| [EVAL_RESULTS.md](backend/docs/EVAL_RESULTS.md) | Evaluation status |
| [INTERVIEW_PREP.md](backend/docs/INTERVIEW_PREP.md) | Walkthrough and question bank |
| [DEMO_SCRIPT.md](backend/docs/DEMO_SCRIPT.md) | Live demonstration steps |
