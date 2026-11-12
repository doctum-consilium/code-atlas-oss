-- code-atlas schema. Replayable: every statement is idempotent.
-- {dimension} is replaced by [models] dimension from the settings.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_search;

CREATE TABLE IF NOT EXISTS repos (
    key TEXT PRIMARY KEY,                 -- "owner/name", or "local/<folder>" without a remote
    host TEXT,                            -- git host of the remote, for source links
    path TEXT NOT NULL,                   -- working tree on this machine
    commit TEXT NOT NULL,
    local_only BOOLEAN NOT NULL DEFAULT FALSE,
    indexed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS files (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    repo TEXT NOT NULL REFERENCES repos (key) ON DELETE CASCADE,
    path TEXT NOT NULL,
    blob TEXT NOT NULL,                   -- git hash: an unchanged file is not read again
    language TEXT NOT NULL,
    type TEXT NOT NULL,
    masked_lines INTEGER[] NOT NULL DEFAULT '{}',
    UNIQUE (repo, path)
);

CREATE TABLE IF NOT EXISTS chunks (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    file_id BIGINT NOT NULL REFERENCES files (id) ON DELETE CASCADE,
    repo TEXT NOT NULL,
    owner TEXT NOT NULL,
    path TEXT NOT NULL,
    language TEXT NOT NULL,
    type TEXT NOT NULL,
    kind TEXT NOT NULL,
    symbol TEXT,
    line_start INTEGER NOT NULL,
    line_end INTEGER NOT NULL,
    text TEXT NOT NULL,
    lexical TEXT NOT NULL,
    embedding vector({dimension}) NOT NULL
);

CREATE INDEX IF NOT EXISTS chunks_file_idx ON chunks (file_id);
CREATE INDEX IF NOT EXISTS chunks_symbol_idx ON chunks (lower(symbol));
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_bm25 ON chunks USING bm25 (id, lexical);

CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY,
    subject TEXT NOT NULL,                -- owner's identity ("sub" claim, or "local")
    title TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS messages (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    model TEXT,
    citations JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS conversations_subject_idx ON conversations (subject, created_at DESC);
CREATE INDEX IF NOT EXISTS messages_conversation_idx ON messages (conversation_id, id);
