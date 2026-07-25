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

*   **Operator Match**: The database is configured with an HNSW (Hierarchical Navigable Small World) index specifically using the `vector_cosine_ops` operator class. 
*   **Query Match**: The retrieval SQL query explicitly uses the `<=>` operator (cosine distance) rather than `<->` (L2 distance), ensuring the query path perfectly matches the index path.
*   **Why it matters**: Using cosine distance aligns precisely with OpenAI's `text-embedding-3-small` output geometry, while the HNSW index ensures sub-millisecond retrieval times even as the chunk table grows to millions of rows.

## 3. Isolated Celery Worker Sessions

Asynchronous document ingestion is handled by Celery to prevent long-running PDF extraction and embedding tasks from blocking the FastAPI event loop.

*   **State Isolation**: The Celery worker module (`worker.py`) instantiates its own isolated SQLAlchemy `create_engine` and `sessionmaker`. 
*   **Why it matters**: It deliberately avoids importing FastAPI's request-scoped `get_db` dependency. Sharing a database connection pool across multiprocessing boundaries is a common anti-pattern that leads to connection pool exhaustion and "no application context" errors under heavy upload load. 

## 4. Langfuse Observability

Aegis integrates Langfuse to monitor the RAG pipeline's behavior in production.

*   **Nested Spans**: The `/query` endpoint wraps the request in a parent trace, with child spans explicitly demarcating the `retrieval` phase (database execution) and the `generation` phase (LLM streaming).
*   **Why it matters**: When auditing a permission denial, administrators can inspect the Langfuse trace to prove that the database returned an empty array during the `retrieval` span, confirming the system behaved correctly and the LLM was never exposed to the restricted text.
