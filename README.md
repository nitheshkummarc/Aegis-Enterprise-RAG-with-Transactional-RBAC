# 🛡️ Aegis: Enterprise RAG with Transactional RBAC

**A production-grade Retrieval-Augmented Generation (RAG) system that enforces Role-Based Access Control (RBAC) at the database layer, not the application layer.**

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16+%20pgvector-336791?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Next.js](https://img.shields.io/badge/Next.js-15-000000?logo=next.js&logoColor=white)](https://nextjs.org/)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## 📖 Overview & The Problem Solved

Standard RAG architectures suffer from a critical security flaw: they dump all enterprise data into a single vector database and rely on LLM prompt instructions or application-layer filtering to hide sensitive information. This leads to data leakage when a junior employee asks about executive compensation or M&A targets.

**Aegis solves this by shifting security from the prompt to the database engine.** 

By denormalizing permission levels (`min_role_level`) directly onto the vector chunks and using PostgreSQL's `pgvector` extension, Aegis ensures that unauthorized chunks are **excluded at the database query boundary** — before they enter the LLM's context window. The retrieval layer prevents unauthorized chunks from being included in generation; that guarantee is specific to this SQL query, not a claim about the system as a whole (an authorized chunk could still contain information a stricter policy would want redacted, and any other endpoint or upload-time misclassification is a separate concern with its own checks).

---

## 🏗️ Core Architecture: Single-Query RBAC

The core thesis of Aegis is that **security and retrieval must happen in the same transactional boundary.** (Not literally "one table scan" — the real query plan is a nested-loop join between `document_chunks` and `documents` for the title lookup. What's actually guaranteed is that the permission filter and the ANN ordering are one SQL statement, not a separate filter step in application code.)

Instead of fetching top-k vectors and filtering them in Python (which is slow and prone to edge-case leaks), Aegis executes an atomic, permission-filtered vector search:

```sql
SELECT text_content, document_id, chunk_index, d.title
FROM document_chunks dc
JOIN documents d ON d.id = dc.document_id
WHERE dc.min_role_level <= :user_role_level  -- RBAC Enforced Here
ORDER BY dc.embedding <=> :query_embedding   -- Cosine Similarity via HNSW
LIMIT 3;
```
*The permission filter and the ANN search are expressed as one query, executed against one of three cumulative partial HNSW indexes (one per role level) — see [Verified query plan](backend/docs/ARCHITECTURE.md#verified-query-plan) for `EXPLAIN (ANALYZE, BUFFERS)` evidence that PostgreSQL's planner actually selects the matching index per role, rather than a claim taken on faith.*

---

## 🛠️ Tech Stack

| Component | Technology | Justification |
| :--- | :--- | :--- |
| **Backend** | Python 3.11, FastAPI | Async-native, high performance, strict Pydantic validation. |
| **Frontend** | Next.js 15 (App Router), Tailwind, Auth.js v5 | Modern SSR, secure credential-based JWT session management. |
| **Database** | PostgreSQL 16 + `pgvector` | Keeps relational metadata and vector embeddings in one transactional boundary. |
| **Vector Index** | HNSW (`vector_cosine_ops`), one cumulative partial index per role level | Sub-millisecond retrieval latency; the per-role split keeps a viewer's search from ever ANN-scanning admin-only chunks. |
| **Async Queue** | Celery + Redis | Decouples heavy PDF parsing/embedding from the HTTP request lifecycle. |
| **Generation** | LangChain `ChatGroq` → Groq (`openai/gpt-oss-120b`, or `qwen/qwen3.6-27b`) | The model is a config value (`GROQ_MODEL`), not a hardcoded SDK call, so swapping candidates is a restart rather than a code change. LangChain wraps **generation only** — never retrieval, which would move authorization out of SQL. |
| **Embeddings** | Groq `nomic-embed-text-v1_5` (OpenAI-compatible endpoint) | One provider, one API key for the whole system. The `openai` package is reused as a generic protocol client pointed at Groq — not a dependency on an OpenAI account. |
| **Observability** | Langfuse (Cloud, v4 SDK) | End-to-end tracing of retrieval latency, token costs, and RBAC enforcement. The generation span is reported by LangChain's callback; retrieval is instrumented by hand. |

---

## ✨ Key Engineering Features

- **🔒 Database-Layer RBAC:** Row-level permission filtering via SQL `WHERE` clauses, eliminating application-layer authorization bugs.
- **🛡️ Enterprise Security Hardening:** Strict Pydantic models (`extra="forbid"`) to prevent mass assignment, `slowapi` rate-limiting on auth endpoints to prevent credential stuffing, JWT algorithm pinning, and extensive `.gitignore` isolation.
- **⚡ Async Ingestion Pipeline:** Celery workers with isolated DB sessions handle table-aware PyMuPDF extraction (detected tables are rendered as markdown so rows/columns survive parsing) and Groq embedding — transient storage failures retry automatically, while corrupt PDFs and extraction errors fail fast with no retry. A periodic cleanup task dead-letters any document orphaned mid-upload.
- **📊 Adversarial Evaluation Harness:** Runs the golden dataset through the real `/retrieval/query` endpoint — real embeddings, real pgvector search, real LLM generation — including SQL injection payloads, malformed JWTs, and privilege escalation attempts, scored against the model's actual output rather than the retrieved chunks alone.
- **📈 Hard Performance Metrics:** Instrumented to measure and report p95 database retrieval latency for the permission-filtered query.
- **👁️ End-to-End Observability:** Langfuse (v4) traces every query — a root span carrying user and role, a hand-instrumented retrieval span recording the role level used in the `WHERE` clause, and a generation span reported by LangChain's own callback.
- **🔁 Swappable Generation:** Generation runs through LangChain `ChatGroq` behind a single `GROQ_MODEL` setting, so evaluating a different model is a restart rather than a code change — while retrieval stays hand-written SQL, keeping authorization out of framework configuration.

---

## 🚀 Quickstart

### Prerequisites
- Docker & Docker Compose
- **A Groq API key** (`GROQ_API_KEY`, free tier) — the only provider credential needed; it covers both generation and embeddings
- (Optional) Langfuse Cloud keys for observability

> **Before first seeding**, confirm the embedding width matches the schema:
> `python -m scripts.verify_embedding_dimensions`. It measures the model's real
> output and tells you what to change if `EMBEDDING_DIMENSIONS` in
> `app/config.py` disagrees — the pgvector column width is not negotiable at
> insert time.

### 1. Clone and Configure
```bash
git clone https://github.com/nitheshkummarc/Aegis-Enterprise-RAG-with-Transactional-RBAC.git
cd Aegis-Enterprise-RAG-with-Transactional-RBAC
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local
# Edit backend/.env and frontend/.env.local to add your API keys
```

### 2. Launch the Backend Stack
```bash
docker-compose up -d --build
```
This brings up Postgres (pgvector), Redis, the FastAPI backend (`:8000`), and
the Celery worker. Migrations run automatically on backend startup.

**The frontend is not containerized** — run it separately:
```bash
cd frontend
npm install
npm run dev
```

### 3. Seed Test Users
```bash
docker-compose exec backend python -m scripts.seed_users
```

### 4. Access the Application
Navigate to [http://localhost:3000](http://localhost:3000). Login with one of the seeded test users:

| Role | Email | Password | Access Level |
| :--- | :--- | :--- | :--- |
| **Admin** | `admin@clearancerag.test` | `admin123` | Can upload docs, view all data. |
| **Manager** | `manager@clearancerag.test` | `manager123` | Can view internal roadmaps, no financials. |
| **Viewer** | `viewer@clearancerag.test` | `viewer123` | Can view public operational docs only. |

---

## 📊 Evaluation & Performance

Aegis is tested against a synthetic corpus with strict cross-contamination checks, using [`eval/run_eval.py`](backend/eval/run_eval.py) — which runs every golden-dataset question through the real `/retrieval/query` endpoint (real embeddings, real pgvector search, real LLM generation) and scores permission compliance and faithfulness against the model's actual output.

The dataset holds **25 questions — 11 boundary cases and 3 adversarial** (forged JWTs, privilege escalation), so a clean run reports out of 25 and 11.

The two metrics measure different things, and the distinction matters:

- **Permission compliance** is scored from `min_role_level` on a direct SQL call, making it structurally independent of the LLM. No model swap can move it. This is the metric that speaks to the security thesis.
- **Faithfulness** is scored against the model's actual generated text — for refusal cases, the exact string `"I do not have access to that information."` A chunk-level check could not tell *"correctly refused"* apart from *"ignored its instructions and answered from parametric knowledge."*

> **⚠️ Current status: no baseline exists.** Generation recently migrated from OpenAI `gpt-4o-mini` to Groq, and a model swap invalidates every generation-dependent metric — nothing carries across it. Figures of "22/22" and "8/8" have circulated for this project; neither was ever produced by the current harness, and neither is arithmetically possible against it. See [`docs/EVAL_RESULTS.md`](backend/docs/EVAL_RESULTS.md) for what is actually measured, what is blocked, and how to regenerate it.

---

## ⚖️ Architectural Trade-offs & Limitations

To maintain architectural purity and focus on the Transactional RBAC thesis, specific decisions were made:

1. **HNSW Approximate Recall vs. Exact Search:** Aegis uses the HNSW index for sub-millisecond latency. HNSW is an Approximate Nearest Neighbor (ANN) algorithm. In edge cases, it might occasionally miss a permitted chunk compared to a brute-force sequential scan. *Mitigation: For <10k chunks, HNSW provides >99% recall. `ivfflat` is also approximate (recall depends on its `probes` parameter and is never exactly 100%) — the only way to guarantee 100% exact recall is to drop the ANN index and run a sequential scan, accepting the latency cost that comes with it.*
2. **No Standalone Vector DB:** We intentionally avoid Pinecone/Qdrant to keep relational metadata (RBAC constraints) tightly coupled with vector embeddings in PostgreSQL, so the permission filter and the ANN search can be one query instead of two systems to keep in sync.
3. **No Multi-Agent Orchestration:** The pipeline is linear and deterministic — `embed → permission-filtered search → generate`. Adopting LangChain for generation did **not** introduce chains, agents, routers or tool calling: every branch in an authorization-sensitive path is a branch that has to be audited. *Cost: no query rewriting, no multi-hop retrieval, no self-correction.*
4. **LangChain Wraps Generation Only:** The idiomatic LangChain RAG pattern (`create_retrieval_chain` over a filtered `as_retriever`) is deliberately rejected, because it would express the role filter as a framework kwarg — moving authorization out of the database and one refactor away from not being applied. *Cost: Aegis forgoes LangChain's retrieval ecosystem and hand-writes what it needs.*
5. **Ordered Clearance Levels Only:** `min_role_level` assumes a totally ordered model. Genuinely orthogonal roles — "Finance" and "Engineering" as peers rather than levels — do not fit an integer comparison and would require a real change, not a bigger number.
6. **Single Provider, Undocumented Endpoint:** Generation and embeddings both run on Groq, so the system needs one key. Groq's embeddings endpoint responds but is **absent from its public API reference**, so it carries more stability risk than a documented one. *Cost: a provider-side change there breaks ingestion and query with no deprecation notice.*

**Full reasoning, rejected alternatives, and the cost of each decision are recorded in [`docs/ENGINEERING_DECISIONS.md`](backend/docs/ENGINEERING_DECISIONS.md).**

---

## 📂 Project Structure

```text
Aegis/
├── backend/
│   ├── app/
│   │   ├── auth/           # JWT generation, Pydantic validation, RBAC dependencies
│   │   ├── core/           # Exceptions, rate limiter, Langfuse wiring (observability.py)
│   │   ├── db/              # SQLAlchemy models, migrations (Alembic + schema.sql)
│   │   ├── documents/      # Presigned upload, document CRUD
│   │   ├── ingestion/      # Celery worker, PyMuPDF parser, chunker, embedder
│   │   └── retrieval/      # Permission-filtered pgvector search, LangChain/Groq generation, SSE
│   ├── docs/               # See "Documentation" below
│   ├── eval/               # Golden dataset, adversarial stress tests, run_eval.py
│   ├── scripts/            # Synthetic corpus generator with cross-contamination checks
│   └── tests/              # Unit, Integration, and Security (RBAC) test suites
├── frontend/               # Next.js 15 App Router, Auth.js v5, SSE Chat UI
├── .github/workflows/      # CI: backend test suite against real Postgres + Redis
└── docker-compose.yml      # Postgres (pgvector), Redis, Backend, Celery Worker
```

---

## 📚 Documentation

All project documentation lives in [`backend/docs/`](backend/docs/).

| Document | What it answers |
| :--- | :--- |
| [**ARCHITECTURE.md**](backend/docs/ARCHITECTURE.md) | **What the system is.** Single-query RBAC enforcement with a verified `EXPLAIN` plan, per-role partial HNSW indexes, the LangChain/Groq generation layer, and the Langfuse v4 span structure. |
| [**METHODOLOGY.md**](backend/docs/METHODOLOGY.md) | **How it is built and verified.** Why the corpus is synthetic, where the authorization boundary is tested, what each evaluation metric can and cannot prove, and the rules for reporting numbers. |
| [**ENGINEERING_DECISIONS.md**](backend/docs/ENGINEERING_DECISIONS.md) | **Why it is shaped this way.** Thirteen decisions with their rejected alternatives and — for each — what the choice actually costs. Plus the open questions that are not yet settled. |
| [**EVAL_RESULTS.md**](backend/docs/EVAL_RESULTS.md) | **What was measured.** Regenerated on every `run_eval.py` run; records which model produced each result. |
| [**DEMO_SCRIPT.md**](backend/docs/DEMO_SCRIPT.md) | A walkthrough demonstrating the RBAC boundary end to end. |

These are written to be honest about limits rather than promotional: the
architecture doc includes a section on how it used to be wrong, and the
decisions doc states the cost of every choice.
