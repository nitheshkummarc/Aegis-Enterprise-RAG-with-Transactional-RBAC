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
| **LLM** | OpenAI (`gpt-4o-mini`, `text-embedding-3-small`) | Optimized for low latency and high instruction-following. |
| **Observability** | Langfuse (Cloud) | End-to-end tracing of retrieval latency, token costs, and RBAC enforcement. |

---

## ✨ Key Engineering Features

- **🔒 Database-Layer RBAC:** Row-level permission filtering via SQL `WHERE` clauses, eliminating application-layer authorization bugs.
- **🛡️ Enterprise Security Hardening:** Strict Pydantic models (`extra="forbid"`) to prevent mass assignment, `slowapi` rate-limiting on auth endpoints to prevent credential stuffing, JWT algorithm pinning, and extensive `.gitignore` isolation.
- **⚡ Async Ingestion Pipeline:** Celery workers with isolated DB sessions handle table-aware PyMuPDF extraction (detected tables are rendered as markdown so rows/columns survive parsing) and OpenAI embedding — transient storage failures retry automatically, while corrupt PDFs and extraction errors fail fast with no retry. A periodic cleanup task dead-letters any document orphaned mid-upload.
- **📊 Adversarial Evaluation Harness:** Runs the golden dataset through the real `/retrieval/query` endpoint — real embeddings, real pgvector search, real LLM generation — including SQL injection payloads, malformed JWTs, and privilege escalation attempts, scored against the model's actual output rather than the retrieved chunks alone.
- **📈 Hard Performance Metrics:** Instrumented to measure and report p95 database retrieval latency for the permission-filtered query.
- **👁️ End-to-End Observability:** Langfuse integration traces every query, separating DB retrieval time from LLM generation latency.

---

## 🚀 Quickstart

### Prerequisites
- Docker & Docker Compose
- An OpenAI API Key
- (Optional) Langfuse Cloud keys for observability

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

> **Note:** The harness was recently rewritten to score against real end-to-end output instead of a keyword-matching approximation. Run `python -m eval.run_eval` to regenerate current numbers — see [`docs/EVAL_RESULTS.md`](backend/docs/EVAL_RESULTS.md) for the latest report and methodology.

---

## ⚖️ Architectural Trade-offs & Limitations

To maintain architectural purity and focus on the Transactional RBAC thesis, specific decisions were made:

1. **HNSW Approximate Recall vs. Exact Search:** Aegis uses the HNSW index for sub-millisecond latency. HNSW is an Approximate Nearest Neighbor (ANN) algorithm. In edge cases, it might occasionally miss a permitted chunk compared to a brute-force sequential scan. *Mitigation: For <10k chunks, HNSW provides >99% recall. `ivfflat` is also approximate (recall depends on its `probes` parameter and is never exactly 100%) — the only way to guarantee 100% exact recall is to drop the ANN index and run a sequential scan, accepting the latency cost that comes with it.*
2. **No Standalone Vector DB:** We intentionally avoid Pinecone/Qdrant to keep relational metadata (RBAC constraints) tightly coupled with vector embeddings in PostgreSQL, so the permission filter and the ANN search can be one query instead of two systems to keep in sync.
3. **No Multi-Agent Orchestration:** The pipeline is linear and deterministic. Routing logic is written in pure FastAPI to keep the execution path transparent and easily auditable.

---

## 📂 Project Structure

```text
Aegis/
├── backend/
│   ├── app/
│   │   ├── auth/           # JWT generation, Pydantic validation, RBAC dependencies
│   │   ├── db/              # SQLAlchemy models, migrations (Alembic + schema.sql)
│   │   ├── documents/      # Presigned upload, document CRUD
│   │   ├── ingestion/      # Celery worker, PyMuPDF parser, chunker, embedder
│   │   └── retrieval/      # Permission-filtered pgvector search, SSE streaming
│   ├── docs/               # ARCHITECTURE.md, DEMO_SCRIPT.md, EVAL_RESULTS.md
│   ├── eval/               # Golden dataset, adversarial stress tests, run_eval.py
│   ├── scripts/            # Synthetic corpus generator with cross-contamination checks
│   └── tests/              # Unit, Integration, and Security (RBAC) test suites
├── frontend/               # Next.js 15 App Router, Auth.js v5, SSE Chat UI
├── .github/workflows/      # CI: backend test suite against real Postgres + Redis
└── docker-compose.yml      # Postgres (pgvector), Redis, Backend, Celery Worker
```
