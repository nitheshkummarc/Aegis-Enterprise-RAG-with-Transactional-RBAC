# ClearanceRAG — Master Build Prompt

**How to use this document:** Feed each phase to your coding agent (Claude Code, Cursor, etc.) one at a time, in order. Do not skip the "Acceptance Criteria" checks — each phase must pass before starting the next. This document is also your source of truth for the README and for interview prep; the "Defensible Claim" boxes are the exact language to use when explaining a feature, and the "Do NOT claim" boxes are language to avoid.

---

## 0. Non-Negotiable Build Rules

1. **No feature is "done" until it has a passing test.** Every phase below ends with tests, not just working code.
2. **No library, model, or tool goes in the README unless it is actually imported and used in committed code.** If a phase's optional item (e.g. reranker) is skipped, it does not appear in the stack list.
3. **No absolutist claims.** Do not write or say "impossible," "immune," "guaranteed," or "100%" about security properties. Use "enforced at the database layer" / "eliminates this class of leak" instead. See Section 9 for exact approved phrasing.
4. **Commit after every phase**, not just at the end. Small, working commits > one giant commit.
5. If you (the coding agent) cannot verify a claim in this doc against actual current library behavior, flag it rather than proceeding on assumption.

---

## 1. Final Tech Stack (locked)

| Layer | Choice |
|---|---|
| Backend | Python 3.11+, FastAPI |
| Frontend | TypeScript, Next.js (App Router), Tailwind CSS, shadcn/ui |
| Database | PostgreSQL 16 + `pgvector` extension (HNSW index) |
| Queue | Redis + Celery |
| Embeddings | OpenAI `text-embedding-3-small` |
| Generation | OpenAI `gpt-5.4-mini` |
| PDF parsing | PyMuPDF |
| Chunking | Recursive character text splitter (LangChain's, or a ~40-line hand-rolled version — agent's choice, but document which) |
| Auth | NextAuth (Auth.js), JWT-based sessions |
| Password hashing | `passlib[bcrypt]` (or the `bcrypt` package directly) — must be used for every password written to `users.password_hash`; never store or compare plaintext |
| Eval | Custom golden-dataset harness (Section 7) — no RAGAS dependency required unless the agent finds it genuinely simplifies things |
| Observability | Langfuse Cloud (free tier) — not self-hosted; see Phase 3 |
| Testing | pytest (backend), Vitest or Jest (frontend, minimal) |

No LangGraph, no multi-agent framework, no standalone vector DB (Pinecone/Qdrant/Weaviate). This is a deliberate scope decision — do not add these.

**Why Langfuse is in scope (and isn't scope creep):** the project's core thesis is "permission-aware retrieval enforced at the database layer." That's an unverifiable claim without a way to see, per request, exactly which chunks were retrieved for which user. Langfuse tracing is what turns "I built RBAC-filtered RAG" from a demo-only claim into something inspectable after the fact — this directly serves the thesis, unlike a reranker or multi-agent orchestration, which don't.

### Required Environment Variables

All of the following must be defined in `.env` and loaded via `pydantic-settings` in `backend/app/config.py`. Do not let the agent invent its own variable names — use exactly these:

```
DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/clearancerag
REDIS_URL=redis://localhost:6379/0
OPENAI_API_KEY=
JWT_SECRET_KEY=
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=60
NEXTAUTH_SECRET=
NEXTAUTH_URL=http://localhost:3000
BACKEND_URL=http://localhost:8000
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=https://cloud.langfuse.com
```

---

## 2. Full Repository Structure

```
clearancerag/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI app entrypoint
│   │   ├── config.py                # env/config loading
│   │   ├── db/
│   │   │   ├── session.py           # SQLAlchemy engine/session
│   │   │   ├── models.py            # User, Document, DocumentChunk
│   │   │   └── migrations/          # Alembic migrations
│   │   ├── auth/
│   │   │   ├── jwt.py
│   │   │   ├── dependencies.py      # get_current_user, require_role
│   │   │   └── routes.py            # /login, /register (or NextAuth callback verification)
│   │   ├── documents/
│   │   │   ├── routes.py            # /upload, /documents, /documents/{id} DELETE
│   │   │   ├── schemas.py           # Pydantic models
│   │   │   └── service.py
│   │   ├── ingestion/
│   │   │   ├── worker.py            # Celery app + task definitions
│   │   │   ├── parser.py            # PyMuPDF text extraction
│   │   │   ├── chunker.py           # text splitting
│   │   │   └── embedder.py          # OpenAI embedding calls
│   │   ├── retrieval/
│   │   │   ├── routes.py            # /query (SSE streaming)
│   │   │   ├── search.py            # permission-filtered pgvector query
│   │   │   ├── prompt.py            # system prompt template
│   │   │   └── generate.py          # OpenAI generation call + streaming
│   │   └── core/
│   │       ├── security.py
│   │       └── exceptions.py
│   ├── tests/
│   │   ├── conftest.py              # fixtures: test db, test users per role, sample docs
│   │   ├── unit/
│   │   │   ├── test_chunker.py
│   │   │   ├── test_jwt.py
│   │   │   ├── test_prompt_template.py
│   │   │   └── test_search_query_builder.py
│   │   ├── integration/
│   │   │   ├── test_upload_flow.py
│   │   │   ├── test_ingestion_worker.py
│   │   │   ├── test_query_flow.py
│   │   │   └── test_auth_routes.py
│   │   └── security/
│   │       ├── test_rbac_enforcement.py   # THE critical test file — see Section 6
│   │       └── test_prompt_injection.py
│   ├── eval/
│   │   ├── golden_dataset.json       # Section 7
│   │   ├── run_eval.py
│   │   └── results/                  # eval run outputs, gitignored except latest
│   ├── scripts/
│   │   └── generate_synthetic_corpus.py   # Section 7.5 — synthetic data generation + cross-contamination check
│   ├── alembic.ini
│   ├── requirements.txt
│   ├── docker-compose.yml
│   └── Dockerfile
├── frontend/
│   ├── app/
│   │   ├── (auth)/login/page.tsx
│   │   ├── (dashboard)/
│   │   │   ├── chat/page.tsx
│   │   │   └── admin/documents/page.tsx
│   │   ├── api/auth/[...nextauth]/route.ts
│   │   └── layout.tsx
│   ├── components/
│   │   ├── ChatWindow.tsx
│   │   ├── SourcesDropdown.tsx
│   │   ├── UploadButton.tsx           # only rendered for admin role
│   │   └── DocumentList.tsx
│   ├── lib/
│   │   ├── api.ts                     # typed fetch wrappers to backend
│   │   └── auth.ts
│   ├── tests/
│   │   └── SourcesDropdown.test.tsx   # minimal — frontend is not the resume focus
│   ├── package.json
│   └── tsconfig.json
├── docs/
│   ├── ARCHITECTURE.md
│   ├── EVAL_RESULTS.md
│   └── DEMO_SCRIPT.md
├── docker-compose.yml              # orchestrates postgres, redis, backend, celery worker
└── README.md
```

---

## 3. Database Schema

```sql
CREATE EXTENSION IF NOT EXISTS vector;

-- Single shared vocabulary for roles. Both users.role and the permission
-- arrays below reference this type, so a typo like 'admn' fails at insert
-- time instead of silently making a chunk unreachable by anyone.
CREATE TYPE user_role AS ENUM ('viewer', 'manager', 'admin');

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role user_role NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    uploaded_by UUID NOT NULL REFERENCES users(id),
    -- min_role_level, not an array: 0 = viewer and above may read it,
    -- 1 = manager and above, 2 = admin only. See the note below for why
    -- this replaced a role array.
    min_role_level SMALLINT NOT NULL CHECK (min_role_level BETWEEN 0 AND 2),
    status TEXT NOT NULL DEFAULT 'processing' CHECK (status IN ('processing', 'ready', 'failed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX documents_uploaded_by_idx ON documents(uploaded_by);

CREATE TABLE document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    text_content TEXT NOT NULL,
    embedding VECTOR(1536) NOT NULL,
    -- Denormalized copy of documents.min_role_level, kept in the SAME
    -- INSERT transaction as the parent document row (see Phase 2). This
    -- is what lets the permission filter and the vector search run in
    -- one table scan instead of a join.
    min_role_level SMALLINT NOT NULL CHECK (min_role_level BETWEEN 0 AND 2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, chunk_index)
);

-- Critical index: without this, permission-filtered vector search
-- degrades to a full sequential scan past a few thousand rows.
-- Using cosine ops (not L2) to match OpenAI's convention and keep
-- similarity scores in an interpretable [0,1]-ish range. Note: for
-- text-embedding-3-small specifically, OpenAI's embeddings are
-- normalized, so cosine and L2 produce mathematically IDENTICAL
-- rankings — this is not a recall improvement, just convention and
-- future-proofing in case a non-normalized embedding model is swapped
-- in later.
CREATE INDEX document_chunks_embedding_hnsw
    ON document_chunks USING hnsw (embedding vector_cosine_ops);

CREATE INDEX document_chunks_min_role_level_idx
    ON document_chunks (min_role_level);
```

**Why `min_role_level` (an integer) instead of an `allowed_roles` array:** the earlier array design required whoever tags a document to remember to list every role that should see it (a viewer-tier doc needed `['admin','manager','viewer']` explicitly). Forgetting one role at ingest time silently removes access for that role — a quiet bug in exactly the direction you don't want (a legitimate user locked out, or worse, an intended-restricted doc accidentally left open if someone lists the wrong roles). A numeric level makes the hierarchy structural instead of manually maintained: `viewer=0, manager=1, admin=2`, and the query becomes `WHERE min_role_level <= :user_role_level`. There's nothing to forget to list.

**Query shape this implies for Phase 3** (update `retrieval/search.py` accordingly):
```sql
SELECT dc.text_content, dc.document_id, dc.chunk_index, d.title
FROM document_chunks dc
JOIN documents d ON d.id = dc.document_id
WHERE dc.min_role_level <= %(user_role_level)s
ORDER BY dc.embedding <=> %(query_embedding)s
LIMIT 3;
```
where `user_role_level` is resolved from the JWT's `role` claim via a small fixed mapping (`{'viewer': 0, 'manager': 1, 'admin': 2}`) in application code — never trust a numeric level sent directly by the client. The `<=>` operator here is cosine distance, matching the `vector_cosine_ops` index above; the `JOIN` to `documents` exists to fetch `title` for the Sources UI (Phase 4) — the chunks table intentionally doesn't duplicate the title.

**Note for the agent:** `min_role_level` is denormalized onto `document_chunks` (not just `documents`) specifically so the permission filter and the vector search happen in the *same table scan* — that's the whole point of the architecture. Do not "normalize" this away by joining to `documents` at query time; that reintroduces the exact coupling problem the design avoids. Also update Section 6's test cases: `test_malformed_allowed_roles_defaults_to_most_restrictive` becomes a test that a `NULL` or out-of-range `min_role_level` is rejected by the `CHECK` constraint at insert time, not silently defaulted at query time — enforcing this at the schema level is stronger than enforcing it in application logic.

---

## 4. Build Phases

### Phase 1 — Foundation (Auth + Schema)
**Build:**
- Docker Compose with Postgres (pgvector image), Redis
- Alembic migration implementing Section 3 schema
- FastAPI app skeleton, JWT auth (`/register`, `/login`), `require_role()` dependency
- Seed script creating one admin, one manager, one viewer test user

**Password hashing:** use `passlib[bcrypt]` (or the `bcrypt` package directly) to hash passwords on `/register` and verify them on `/login`. Never store or compare plaintext passwords, and never invent a hashing scheme — this is exactly the kind of thing where "roll your own" is a real security bug, not a stylistic choice.

**Tests to write in this phase:**
- `tests/unit/test_jwt.py` — token creation/verification, expired token rejection
- `tests/integration/test_auth_routes.py` — login success/failure, role appears correctly in token claims

**Auth wiring — read before building (this is the highest-risk integration point in the whole project):**
NextAuth (Auth.js v5) must use the **Credentials provider**, not an OAuth provider setup. The flow is: the frontend login form calls the `signIn("credentials", { email, password })` function; NextAuth's `authorize()` callback makes the actual HTTP call to FastAPI's `/login` endpoint; FastAPI validates and returns the JWT; NextAuth's `jwt` callback stores that JWT inside its own encrypted session token (do NOT store it in `localStorage`). For all subsequent frontend calls to FastAPI, extract the JWT from the NextAuth session and send it as `Authorization: Bearer <token>`. Do not attempt to make FastAPI an OAuth provider — that's solving a different problem than this project has. Use Auth.js v5 syntax specifically (the `auth.ts` config file, not v4's `[...nextauth].js` options object) — v5 was a breaking rewrite and mixing syntaxes will not work.

**Migration strategy:** for the migration that creates the `vector` extension, tables, and the HNSW/GIN indexes from Section 3, do not rely on SQLAlchemy's autogenerate — write it as a raw-SQL Alembic migration via `op.execute(...)` using the exact SQL in Section 3. Autogenerate frequently mishandles extension creation and non-standard index types like `hnsw`.

**ORM note:** define the `embedding` column using the actual `pgvector` Python package (`from pgvector.sqlalchemy import Vector`, e.g. `mapped_column(Vector(1536))`), not a plain `ARRAY(Float)`. A plain array column will not support the `<->` distance operator or the HNSW index.

**CORS — add this or Phase 4 fails silently:** Next.js runs on `localhost:3000`, FastAPI on `localhost:8000` — different origins, so without CORS headers every frontend call to the backend will be blocked by the browser with no obvious server-side error. In `main.py`, add `CORSMiddleware` from `fastapi.middleware.cors`, allowing `http://localhost:3000` in dev and your production frontend URL later. Do this in Phase 1, not Phase 4 — it's easy to forget once you're deep into frontend work and debugging what looks like a networking issue.

**Docker image — use the pgvector-enabled image, not plain Postgres:** the `docker-compose.yml` Postgres service must use `pgvector/pgvector:pg16` (or a pinned version tag like `pgvector/pgvector:0.8.5-pg16`), not `postgres:16`. The standard Postgres image does not include the `pgvector` extension, and `CREATE EXTENSION vector` will fail against it.

**Acceptance criteria:** A viewer and an admin can both log in and get back a JWT with the correct `role` claim, and the frontend can complete a full login round-trip through NextAuth's Credentials provider. `pytest tests/unit tests/integration/test_auth_routes.py` passes.

---

### Phase 2 — Async Ingestion Pipeline
**Build:**
- `/documents/upload` endpoint: admin-only, saves file, creates `documents` row with `status='processing'`, pushes Celery task, returns `202`
- **File size limit note:** FastAPI/Starlette itself has no default request-body size limit, so local dev with plain Uvicorn needs no extra config. But if you put Nginx in front for anything beyond local dev, set `client_max_body_size 50M` (or appropriate) — otherwise a large PDF upload returns `413` before it even reaches FastAPI. Document this in `docs/ARCHITECTURE.md` even if you don't deploy it, since it's a real production-readiness gap worth naming proactively.
- Celery worker: PyMuPDF extraction → chunk (500 tokens, 50 overlap) → embed via `text-embedding-3-small` → batch insert into `document_chunks` with `min_role_level` copied from the parent document's `min_role_level` → update `documents.status='ready'`. Do the chunk inserts and the status update in a single transaction — a worker crash mid-batch should never leave `status='ready'` with only some chunks written.
- **Worker DB session:** Celery runs in its own process, separate from the FastAPI app. `worker.py` must initialize its own SQLAlchemy engine/session scoped to the worker process — do not import and reuse FastAPI's request-scoped session. Sharing a session/connection pool across the two processes causes "no application context" errors or connection-pool exhaustion under load.
- Retry logic: if OpenAI embedding call fails (rate limit), Celery retries with exponential backoff (max 3 attempts), then sets `status='failed'`
- Error handling: wrap the PyMuPDF extraction step in its own try/except, separate from the OpenAI retry logic. A corrupt or unreadable PDF is not a transient failure — do not retry it. Catch the exception, set `documents.status='failed'`, log the error with the document ID, and stop. Only the OpenAI call should have retry-with-backoff; the parsing step should fail fast once.

**Tests to write in this phase:**
- `tests/unit/test_chunker.py` — chunk boundaries, overlap correctness, edge case of a document shorter than one chunk
- `tests/integration/test_upload_flow.py` — non-admin gets 403 on upload; admin upload returns 202 immediately (assert response time, not just status code)
- `tests/integration/test_ingestion_worker.py` — run the worker task synchronously against a small sample PDF fixture, assert chunks land in DB with `min_role_level` matching the parent document, assert failure path sets `status='failed'` when embedding call is mocked to raise

**Acceptance criteria:** Uploading a sample PDF as admin results in rows in `document_chunks` with correct role tags within the worker's processing time. All new tests pass.

---

### Phase 3 — Permission-Aware Retrieval + Generation
**Build:**
- `retrieval/search.py`: builds and executes the SQL from Section 3's design —
  ```sql
  SELECT dc.text_content, dc.document_id, dc.chunk_index, d.title
  FROM document_chunks dc
  JOIN documents d ON d.id = dc.document_id
  WHERE dc.min_role_level <= %(user_role_level)s
  ORDER BY dc.embedding <=> %(query_embedding)s
  LIMIT 3;
  ```
  Note the `<=>` (cosine distance) operator here matches `vector_cosine_ops` on the HNSW index in Section 3 — the query operator and the index opclass must agree, or the index won't be used at all. The `JOIN` to `documents` is required to get `title` for the Sources dropdown — without it, the SSE payload's `sources[].title` field has nothing to populate, and Phase 4 will either crash or need to fake it.
- `retrieval/prompt.py`: strict system prompt (Section 5)
- `retrieval/generate.py`: calls `gpt-5.4-mini`, streams via SSE
- `/query` route: embeds user query → permission-filtered search → generation → stream response + `chunk_ids` used
- **Langfuse tracing:** use **Langfuse Cloud's free tier** (cloud.langfuse.com), not self-hosted. Self-hosting Langfuse means running Postgres + Redis + ClickHouse + a web service of its own — turning a lightweight addition into a second multi-service stack for no real benefit at portfolio scale. Sign up, get `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and set `LANGFUSE_HOST=https://cloud.langfuse.com` in `.env`. Do not add any Langfuse services to `docker-compose.yml`. Wrap the `/query` flow in a Langfuse trace with two explicitly named spans — `"1. Permission-Filtered Retrieval"` and `"2. LLM Generation"` — so the dashboard clearly separates database lookup time from LLM latency. Log the user's role and chunk count on the retrieval span; log the model name (`gpt-5.4-mini`), input, output, and token usage on the generation span. This trace is what lets you show, per request, exactly which chunks a given user's role was allowed to see — it's the evidence behind the RBAC claim, not just a nice-to-have.

**SSE payload format (define this exactly, or the frontend in Phase 4 won't know how to parse the stream):**
```
data: {"type": "token", "text": "partial answer chunk"}\n\n
data: {"type": "done", "sources": [{"document_id": "...", "title": "...", "chunk_id": "..."}]}\n\n
```
The `done` event (with the `sources` array, empty if the query was refused) must always be the final event before the stream closes. The frontend's `SourcesDropdown` component reads only from this final event, never accumulates sources from `token` events.

**Tests to write in this phase:**
- `tests/unit/test_search_query_builder.py` — the SQL builder produces a parameterized query (never string-interpolates the role — SQL injection check), correct `LIMIT`
- `tests/integration/test_query_flow.py` — end-to-end: viewer queries and gets an answer sourced only from viewer-accessible chunks
- `tests/security/test_rbac_enforcement.py` — **this is the most important test file in the repo.** See Section 6 for exact required cases.

**Acceptance criteria:** A viewer question about an admin-only document returns "I do not have access to that information," with zero chunk IDs returned. All tests pass, especially `test_rbac_enforcement.py`.

---

### Phase 4 — Frontend
**Build:**
- NextAuth wired to backend JWT — follow the Credentials-provider flow specified in Phase 1 exactly. Do not use `next-auth/react`'s `signIn` function to call FastAPI directly; `signIn("credentials", {...})` triggers NextAuth's own `authorize()` callback, which is what calls FastAPI internally. Everywhere else in the app, use a plain `fetch` wrapper (`lib/api.ts`) that attaches the `Authorization: Bearer` header from the current session.
- Chat UI with SSE streaming render, parsing the `token`/`done` event format from Phase 3
- Sources dropdown (renders `chunk_ids` → document titles)
- Role-conditional UI: upload button and admin dashboard hidden for non-admins (client-side hiding is UX only — the real enforcement is Phase 3's SQL filter; do not treat hiding the button as a security control)

**Tests:** minimal frontend tests are fine — one component test for `SourcesDropdown` rendering correctly with 0 and 3 sources. Frontend is not where your resume claims live for this project; don't over-invest here.

**Acceptance criteria:** Manual demo works: admin uploads confidential doc, viewer asks about it, UI shows denial with no sources dropdown; admin asks and sees the answer with sources.

---

### Phase 5 — Evaluation Harness
**Build:**
- `eval/golden_dataset.json`: minimum 20 question/answer pairs, each tagged with (a) expected answer or expected refusal, (b) which role is asking, (c) which document(s) are relevant. Include at least 5 cases specifically designed to test permission boundaries (a viewer asking about admin-only content, expecting refusal).
- **Prerequisite — seed before you eval:** `run_eval.py` must first trigger ingestion of the synthetic corpus (Section 7.5) into the eval database, or assert it's already seeded and fail loudly with a clear message if not. `relevant_doc_ids` in the golden dataset must exactly match the titles/IDs of the seeded documents. An empty DB will silently make every question "pass" the refusal cases and fail every real-answer case — don't let that go unnoticed.
- `eval/run_eval.py`: runs each question through the real `/query` pipeline (not mocked), scores:
  - **Faithfulness**: does the answer only contain information present in the retrieved chunks? (LLM-as-judge with `gpt-5.4-mini`, or manual scoring — pick one and say which in the README)
  - **Permission compliance**: for the boundary-test cases, did the system correctly refuse? This should be a hard pass/fail, not a judged score — you can check this programmatically against `chunk_ids` returned (must be empty on a correct refusal).
- Output: `eval/results/latest.json` + a human-readable summary written to `docs/EVAL_RESULTS.md`
Phase 5 (Eval Harness):
Micro-Gap: The prompt says run_eval.py "runs each question through the real /query pipeline". However, /query requires a valid JWT. The prompt doesn't explicitly tell the agent how to authenticate the eval script.
Fix: Add this sentence to Phase 5: "The run_eval.py script must authenticate its requests to the /query endpoint by generating valid JWTs for the seeded test users (viewer, manager, admin) and passing them in the Authorization: Bearer <token> header based on the asking_role in the golden dataset."

**Acceptance criteria:** `python eval/run_eval.py` runs against a seeded test dataset and produces a report. Permission-compliance cases must be 100% pass — if any leak, this is a blocking bug, not a tuning issue.

---

### Phase 6 — Docs and Demo Prep
**Build:**
- `docs/ARCHITECTURE.md` — the Section 8 language, diagrams optional (Excalidraw export is fine)
- `docs/DEMO_SCRIPT.md` — the exact 2-minute walkthrough: login as admin → upload confidential doc → login as viewer → ask about it → show denial → login as admin → ask same question → show answer + sources
- `README.md` — stack table, setup instructions, `docker-compose up` quickstart, link to `EVAL_RESULTS.md`

---

## 5. System Prompt (exact text to use in `retrieval/prompt.py`)

```
You are an enterprise assistant. Answer the user's question using ONLY the
provided context below. If the answer is not explicitly present in the
context, reply exactly with: "I do not have access to that information."
Do not use outside knowledge. Do not speculate.

Context:
{context}

Question: {question}
```

---

## 6. Required Test Cases in `tests/security/test_rbac_enforcement.py`

This file is the one you'll be asked to walk through in an interview. It must include, at minimum:

1. `test_viewer_cannot_retrieve_admin_only_chunks` — seed an admin-only doc, query as viewer, assert `chunk_ids == []` and response is the exact refusal string.
2. `test_manager_can_retrieve_manager_and_viewer_docs_not_admin_only` — role hierarchy check.
3. `test_role_change_takes_effect_immediately` — change a user's role in the DB mid-test, issue a new query, assert the new role's permissions apply (this proves there's no caching/staleness bug in the permission path).
4. `test_deleted_document_chunks_are_unretrievable` — delete a document, assert its chunks are gone from query results (cascade delete works).
5. `test_invalid_min_role_level_rejected_at_insert` — attempt to insert a chunk with `min_role_level=NULL` or `min_role_level=5` (out of range) and assert the database rejects it via the `CHECK` constraint, not application-layer validation. This is the fail-closed guarantee: it's enforced at the schema level, so it holds even if a future code path forgets to validate.
6. `test_sql_injection_via_role_param_is_impossible` — attempt to pass a crafted role string (e.g. `"viewer' OR '1'='1"`) through the auth layer and assert it's rejected before reaching the SQL layer (parameterized queries should make this moot, but the test proves it).

This is also the section to point to directly when someone asks "how do you know your permission system actually works" — the answer is "these six tests," not "I tried it manually."

---

## 7. Golden Dataset Shape (`eval/golden_dataset.json`)

```json
[
  {
    "id": "q001",
    "question": "What is the standard PTO policy?",
    "asking_role": "viewer",
    "relevant_doc_ids": ["hr_policy_v1"],
    "expected_behavior": "answer",
    "expected_answer_contains": ["15 days", "annual"]
  },
  {
    "id": "q002",
    "question": "What was discussed in the Q3 executive compensation review?",
    "asking_role": "viewer",
    "relevant_doc_ids": ["exec_comp_confidential"],
    "expected_behavior": "refuse"
  }
]
```
Aim for roughly 60% normal-answer cases and 40% permission-boundary cases — the boundary cases are the ones that matter most for this project's thesis.

---

## 7.5. Synthetic Test Data

Use a synthetically generated corpus, not real company documents or a public dataset. Reasoning to actually understand (not recite): real confidential-style data shouldn't be sent to an external LLM API for a portfolio project, and public datasets don't have natural permission tiers, so you can't test RBAC against them without engineering the boundary yourself.

**Build:**
- Define a fictional company (e.g. "Nexus Logistics") with 3 roles and a handful of document types per role.
- Generate viewer-tier docs (operational, zero financial terms), manager-tier docs (roadmaps, internal metrics), admin-tier docs (financials, comp, M&A-style content).
- Write a cross-contamination check script: scan lower-tier docs for higher-tier keywords (revenue figures, salary numbers, deal names); regenerate if found.
- Run the final text through the same PyMuPDF + chunker pipeline the production system uses, so eval chunk boundaries match real usage.

Keep this data-generation script and the cross-contamination checker in the repo (`scripts/generate_synthetic_corpus.py`) — if you claim this process in an interview, you should be able to show the code that does it, not just describe it.

## 8. Predicted Agent Failure Modes — Watch For These While Building

Even with the constraints above, coding agents commonly make these specific mistakes on this stack. Check for them explicitly after each phase:

1. **Wrong Vector column type** — defining `embedding` as `ARRAY(Float)` instead of `pgvector`'s `Vector` type. Breaks the `<->` operator and the HNSW index silently (it may still run, just without using the index).
2. **NextAuth v4 syntax leaking in** — agent training data has far more v4 examples than v5. Watch for `pages: { signIn: '/login' }`-style config or `[...nextauth].js` instead of the v5 `auth.ts` pattern.
3. **`signIn()` misuse** — agent tries to point `next-auth/react`'s `signIn` at the FastAPI URL directly instead of routing through NextAuth's own `authorize()` callback.
4. **Silent index-less queries** — agent writes the correct SQL but forgets the HNSW index migration, so the query works in a 20-row dev DB and would fall over at real scale. Check `EXPLAIN ANALYZE` on the retrieval query before calling Phase 3 done.

## 9. Approved Language for README / Interview (do not deviate)

| Instead of (overclaim) | Say (defensible) |
|---|---|
| "Mathematically impossible for the LLM to leak data" | "The retrieval layer enforces RBAC via SQL filtering before any chunk reaches the LLM's context window, which eliminates prompt-injection-based leakage of unauthorized content." |
| "Immune to prompt injection" | "Immune to *retrieval-layer* leaks via prompt injection — the LLM cannot be tricked into revealing content it was never given, because permission filtering happens at the database layer, not the prompt layer." |
| "Guaranteed zero hallucinations" | "Reduced hallucination risk via strict grounding prompt and small, high-relevance context window; measured via the eval harness in `docs/EVAL_RESULTS.md`." |
| "Production-ready" | "Built with production patterns (async ingestion, retry logic, RBAC-at-the-database-layer) — not yet load-tested at production scale." (Only drop this caveat if you actually load test it.) |

If asked "what would you do differently for real production," have a real answer ready: rate limiting on `/query`, audit logging of every retrieval (who accessed what chunk, when — important for compliance use cases you cite), and horizontal scaling of Celery workers.

---

## 10. What's Deliberately Out of Scope (say this proactively, don't wait to be asked)

- No cross-encoder reranker — top-3 HNSW retrieval was sufficient at this scale; the tradeoff (latency vs. marginal relevance gain) was a conscious call, not an oversight.
- No multi-agent orchestration — the pipeline is linear by design; RBAC enforcement is easier to reason about and test without a decision-making agent in the loop.
- No standalone vector DB — pgvector keeps permissions and vectors transactionally consistent; this was the central architectural bet of the project.
- No fine-tuning — off-the-shelf embeddings and generation were sufficient for the demonstrated use case.

---

## Build Order Summary (paste this into your agent first if you want it to plan before coding)

1. Phase 1: Foundation (auth, schema, docker-compose) + its tests
2. Phase 2: Ingestion pipeline + its tests
3. Phase 3: Retrieval/generation + its tests (especially Section 6)
4. Phase 4: Frontend
5. Phase 5: Eval harness
6. Phase 6: Docs + demo script

Do not start Phase 4 before Phase 3's `test_rbac_enforcement.py` passes completely. The backend's correctness is the entire point of this project; the frontend is presentation.