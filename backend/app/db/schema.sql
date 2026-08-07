-- =============================================================================
-- ClearanceRAG: Full Database Schema
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
    embedding vector(1536) NOT NULL,
    min_role_level SMALLINT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),

    CONSTRAINT uq_document_chunk_index UNIQUE (document_id, chunk_index),
    CONSTRAINT ck_document_chunks_min_role_level CHECK (min_role_level BETWEEN 0 AND 2)
);

-- =============================================================================
-- Indexes
-- =============================================================================

-- HNSW vector index for cosine distance nearest-neighbor search.
-- m=16, ef_construction=64 are reasonable starting defaults.
--
-- WARNING: This index does NOT guarantee efficient combined filtering with
-- the min_role_level WHERE clause. pgvector HNSW is an ANN index; it does
-- not natively support efficient composite filtering the way a B-tree does.
-- Run EXPLAIN ANALYZE on the permission_filtered_search query once you have
-- >10K chunks to verify the planner is actually using this index under the
-- role filter. If it falls back to a sequential scan, consider:
--   (a) pgvector 0.7+ iterative/filtered index scan support
--   (b) Partial HNSW indexes per role level
--   (c) Pre-filtering with a B-tree index on min_role_level
CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding
ON document_chunks
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- B-tree index on min_role_level for the WHERE filter in permission queries.
-- This helps the planner consider a pre-filter strategy before the ANN scan.
CREATE INDEX IF NOT EXISTS idx_document_chunks_role_level
ON document_chunks (min_role_level);

-- B-tree index on document_id for cascading deletes and chunk lookups.
CREATE INDEX IF NOT EXISTS idx_document_chunks_document_id
ON document_chunks (document_id);
