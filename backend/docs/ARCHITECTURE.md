# Aegis Architecture

Aegis is an enterprise Retrieval-Augmented Generation (RAG) system built with a core thesis: **security must be enforced at the database layer, not the application layer.** 

This document outlines the architectural decisions that enable secure, permission-aware RAG without sacrificing retrieval speed or system reliability.

## 1. Single-Table-Scan RBAC Enforcement

The primary vulnerability in many enterprise RAG systems is fetching the top-k vectors first, and applying permission filters in-memory afterwards. This can lead to "empty response" bugs if all top-k documents are restricted, or complex multi-round retrieval loops.

Aegis solves this by enforcing Role-Based Access Control (RBAC) at the database layer during the vector scan itself.

*   **Denormalized Permissions**: The `min_role_level` is stored directly on the `document_chunks` table.
*   **Unified Query**: When a user queries the system, the vector similarity and the permission filter are executed in a single, atomic SQL query.
    ```sql
    SELECT text_content 
    FROM document_chunks 
    WHERE min_role_level <= :user_role_level 
    ORDER BY embedding <=> :query_embedding 
    LIMIT 3;
    ```
*   **Why it matters**: This guarantees that the system only retrieves chunks the user is explicitly authorized to see. If a viewer searches for admin-level content, the database strictly returns 0 results, allowing the LLM to cleanly refuse the prompt without being exposed to sensitive data.

## 2. HNSW Indexing for Cosine Distance

To support fast similarity search at scale, Aegis utilizes PostgreSQL with the `pgvector` extension.

*   **Operator Match**: The database is configured with HNSW (Hierarchical Navigable Small World) indexes specifically using the `vector_cosine_ops` operator class.
*   **Query Match**: The retrieval SQL query explicitly uses the `<=>` operator (cosine distance) rather than `<->` (L2 distance), ensuring the query path perfectly matches the index path.
*   **Per-role partial indexes**: A single HNSW index over the whole table doesn't natively combine with the `min_role_level` filter — the planner can end up ANN-scanning chunks a role isn't even allowed to see, only to discard them post-filter. Since roles are a fixed 3-tier set, Aegis instead builds one *cumulative partial* HNSW index per level (`WHERE min_role_level <= 0/1/2`): a viewer's query only ever scans public content, a manager's scans public+internal, and admin's covers everything. This keeps ANN scan cost proportional to what the querying role can actually see, not the whole table.
*   **Why it matters**: Using cosine distance aligns precisely with OpenAI's `text-embedding-3-small` output geometry, and the per-role partial indexes keep retrieval fast for lower-privilege roles even as the admin-only tier of the corpus grows large.

## 3. Isolated Celery Worker Sessions

Asynchronous document ingestion is handled by Celery to prevent long-running PDF extraction and embedding tasks from blocking the FastAPI event loop.

*   **State Isolation**: The Celery worker module (`worker.py`) instantiates its own isolated SQLAlchemy `create_engine` and `sessionmaker`. 
*   **Why it matters**: It deliberately avoids importing FastAPI's request-scoped `get_db` dependency. Sharing a database connection pool across multiprocessing boundaries is a common anti-pattern that leads to connection pool exhaustion and "no application context" errors under heavy upload load. 

## 4. Table-Aware PDF Extraction

PyMuPDF's plain `page.get_text()` reads a table cell-by-cell, left-to-right and top-to-bottom, as flat prose — a revenue-by-region table becomes an unlabeled run of numbers, with each value detached from its row/column label.

*   **Detection**: Each page is also passed through PyMuPDF's `find_tables()`, and any detected table is additionally rendered as a markdown table appended to that page's text.
*   **Why it matters**: Chunking and embedding now have a coherent, row-labeled version of every detected table to work with, not just the scrambled prose version. Table detection is best-effort and wrapped so a page it misjudges never breaks plain text extraction for that page.

## 5. Langfuse Observability

Aegis integrates Langfuse to monitor the RAG pipeline's behavior in production.

*   **Nested Spans**: The `/query` endpoint wraps the request in a parent trace, with child spans explicitly demarcating the `retrieval` phase (database execution) and the `generation` phase (LLM streaming).
*   **Why it matters**: When auditing a permission denial, administrators can inspect the Langfuse trace to prove that the database returned an empty array during the `retrieval` span, confirming the system behaved correctly and the LLM was never exposed to the restricted text.

### Known Trade-off: HNSW Approximate Recall vs. Exact Search
Aegis uses the HNSW (Hierarchical Navigable Small World) index for sub-millisecond vector retrieval. HNSW is an Approximate Nearest Neighbor (ANN) algorithm. In edge cases where a permitted chunk is located in a distant graph cluster, HNSW might occasionally miss it compared to a brute-force sequential scan.
- **Mitigation:** For this project's scale (<10k chunks), HNSW provides >99% recall with a fraction of the latency. If absolute 100% recall were a strict compliance requirement (e.g., legal discovery), we would swap the index type to `ivfflat` with a high `lists` parameter, accepting a latency trade-off for guaranteed exactness.

