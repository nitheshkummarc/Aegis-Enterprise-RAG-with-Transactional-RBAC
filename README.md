# Aegis: Enterprise RAG with Transactional RBAC

Aegis is a production-grade Retrieval-Augmented Generation (RAG) system built with a single, uncompromising security thesis: **access control must be enforced at the database layer.**

By filtering permissions natively during the vector scan using PostgreSQL and `pgvector`, Aegis prevents sensitive data chunks from ever reaching the LLM's context window. This eliminates the "empty response" bugs and security leaks common in application-layer filtering.

## 🚀 Quickstart

1. **Clone and setup**:
   ```bash
   git clone https://github.com/nitheshkummarc/Aegis-Enterprise-RAG-with-Transactional-RBAC.git
   cd Aegis-Enterprise-RAG-with-Transactional-RBAC
   ```

2. **Configure Environment**:
   Copy `.env.example` to `.env` and fill in your `OPENAI_API_KEY`.
   *(Optional)* Fill in Langfuse keys for observability tracing.

3. **Launch the Stack**:
   ```bash
   docker-compose up -d --build
   ```

4. **Access the App**:
   Navigate to `http://localhost:3000` and login with one of the seeded test users:
   * **Admin**: `admin@clearancerag.test` / `admin123`
   * **Manager**: `manager@clearancerag.test` / `manager123`
   * **Viewer**: `viewer@clearancerag.test` / `viewer123`

## 🛠️ Tech Stack

| Component | Technology |
| :--- | :--- |
| **Frontend** | Next.js 15 (App Router), Tailwind CSS, Auth.js v5 (NextAuth) |
| **Backend** | FastAPI, Python 3.11, SQLAlchemy |
| **Database & Vector Store** | PostgreSQL 16, `pgvector` (HNSW indexing) |
| **Async Processing** | Celery, Redis |
| **LLM & Embeddings** | OpenAI (`gpt-4o-mini`, `text-embedding-3-small`) |
| **Observability** | Langfuse |

## 📊 Evaluation Results

The architecture is rigorously tested against a synthetic corpus with strict cross-contamination checks. 
You can view the full 100% passing results here: [EVAL_RESULTS.md](backend/docs/EVAL_RESULTS.md).

## 🛡️ Core Security Concept

Aegis solves permission-aware RAG by denormalizing `min_role_level` directly onto the `document_chunks` table. 

Instead of relying on LLM prompt instructions or fetching top-k vectors to filter them in-memory, the system executes an atomic SQL query:

```sql
SELECT text_content 
FROM document_chunks 
WHERE min_role_level <= :user_role_level 
ORDER BY embedding <=> :query_embedding;
```

This guarantees that security is **enforced at the database layer**. It is the most robust and defensible way to ensure sensitive data is physically incapable of leaking into an unauthorized LLM prompt context.

## 🚫 Deliberately Out of Scope

To maintain architectural purity and focus on the Transactional RBAC thesis, the following enterprise features were deliberately omitted:

*   **No Multi-Agent Orchestration**: We do not use LangChain or LlamaIndex. The routing and retrieval logic is written in pure Python/FastAPI to keep the execution path transparent and easily auditable.
*   **No Standalone Vector DB**: We do not use Pinecone, Weaviate, or Qdrant. By using PostgreSQL with `pgvector`, we keep relational metadata (like RBAC constraints) tightly coupled with the vector embeddings, enabling a true single-table-scan.
*   **No Reranker**: While a cross-encoder reranker improves retrieval accuracy, it introduces a secondary filtering step that obscures the core premise: proving that the database itself handles the security boundary perfectly.

---
*For a detailed look at the system internals, please read the [Architecture Document](backend/docs/ARCHITECTURE.md) and the [Demo Script](backend/docs/DEMO_SCRIPT.md).*
