-- =============================================================================
-- Aegis: Full Database Schema
-- =============================================================================
-- Run this script in your Supabase SQL Editor (or any PostgreSQL 15+ with
-- pgvector installed) to set up the database from scratch.
--
-- This is the single source of truth for the schema. It matches the
-- SQLAlchemy ORM models in backend/app/db/models.py exactly.
-- =============================================================================

-- 1. Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Create the Role Enum
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'user_role') THEN
        CREATE TYPE user_role AS ENUM ('viewer', 'manager', 'admin');
    END IF;
END$$;

-- 3. Users Table
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role user_role NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

-- 4. Documents Table
CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    uploaded_by UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    min_role_level SMALLINT NOT NULL,
    status TEXT NOT NULL DEFAULT 'processing',

    -- Supabase Storage object key: {user_id}/{document_id}/{uuid}.pdf
    -- User-controlled filename content never reaches this path.
    object_key TEXT,

    -- Original filename stored as metadata only — never used to construct
    -- a storage path or object key.
    original_filename TEXT,

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),

    CONSTRAINT ck_documents_min_role_level CHECK (min_role_level BETWEEN 0 AND 2),
    CONSTRAINT ck_documents_status CHECK (status IN ('processing', 'ready', 'failed'))
);

-- 5. Document Chunks Table (The Vector Store)
CREATE TABLE IF NOT EXISTS document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    text_content TEXT NOT NULL,
    -- Width must equal EMBEDDING_DIMENSIONS in app/config.py, which must
    -- equal the real output width of GROQ_EMBEDDING_MODEL. Verify with
    -- `python -m scripts.verify_embedding_dimensions`.
    embedding vector(768) NOT NULL,
    min_role_level SMALLINT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),

    CONSTRAINT uq_document_chunk_index UNIQUE (document_id, chunk_index),
    CONSTRAINT ck_document_chunks_min_role_level CHECK (min_role_level BETWEEN 0 AND 2)
);

-- =============================================================================
-- Indexes
-- =============================================================================

-- HNSW vector indexes for cosine distance nearest-neighbor search.
-- m=16, ef_construction=64 are reasonable starting defaults.
--
-- One plain HNSW index over the whole table does NOT guarantee efficient
-- combined filtering with the min_role_level WHERE clause — pgvector HNSW
-- is an ANN index and doesn't natively support composite filtering the way
-- a B-tree does. At scale, a manager-level query still risks the planner
-- ANN-scanning admin-only chunks only to discard them post-filter.
--
-- Instead of one full index, we build one CUMULATIVE PARTIAL HNSW index per
-- role level (roles are a fixed 3-tier set — viewer=0/manager=1/admin=2 —
-- so this is 3 indexes, not N). Each index only covers the chunks that
-- tier can see, so a viewer's search only ever ANN-scans public content,
-- a manager's only scans public+internal, and admin's covers everything
-- (equivalent to the old single full index). Query-side, nothing changes:
-- WHERE min_role_level <= :user_role_level matches exactly one of these
-- partial predicates for any of the 3 valid role levels.
--
-- Run EXPLAIN ANALYZE on permission_filtered_search once the corpus is
-- large (>10K chunks) to confirm the planner is actually choosing the
-- matching partial index rather than falling back to a sequential scan.
CREATE INDEX IF NOT EXISTS idx_document_chunks_hnsw_level0
ON document_chunks
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64)
WHERE min_role_level <= 0;

CREATE INDEX IF NOT EXISTS idx_document_chunks_hnsw_level1
ON document_chunks
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64)
WHERE min_role_level <= 1;

CREATE INDEX IF NOT EXISTS idx_document_chunks_hnsw_level2
ON document_chunks
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64)
WHERE min_role_level <= 2;

-- Drop the old single full-table index if it exists (superseded by
-- idx_document_chunks_hnsw_level2 above, which covers the same rows).
DROP INDEX IF EXISTS idx_document_chunks_embedding;

-- B-tree index on min_role_level for the WHERE filter in permission queries.
-- This helps the planner consider a pre-filter strategy before the ANN scan.
CREATE INDEX IF NOT EXISTS idx_document_chunks_role_level
ON document_chunks (min_role_level);

-- B-tree index on document_id for cascading deletes and chunk lookups.
CREATE INDEX IF NOT EXISTS idx_document_chunks_document_id
ON document_chunks (document_id);
