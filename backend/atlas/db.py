"""PostgreSQL access (ParadeDB: pgvector + pg_search)."""

from __future__ import annotations

from importlib import resources

import psycopg
from psycopg_pool import ConnectionPool


class DimensionMismatch(RuntimeError):
    """The index was built with another vector dimension than the settings."""


def migrate(connection: psycopg.Connection, dimension: int) -> None:
    """Apply the schema (idempotent) and check the vector dimension."""
    if not 1 <= dimension <= 16000:
        raise ValueError(f"Unsupported vector dimension: {dimension}")
    template = resources.files("atlas").joinpath("sql/001_schema.sql").read_text(encoding="utf-8")
    with connection.cursor() as cursor:
        cursor.execute(template.replace("{dimension}", str(int(dimension))).encode())
        cursor.execute(
            "SELECT atttypmod FROM pg_attribute "
            "WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'"
        )
        row = cursor.fetchone()
    connection.commit()
    if row and int(row[0]) != dimension:
        raise DimensionMismatch(
            f"The index holds {row[0]}-dimension vectors but the settings say {dimension}. "
            "Re-create the database (or restore the previous embedder) before indexing."
        )


def connect(dsn: str) -> psycopg.Connection:
    """Plain connection (command line)."""
    return psycopg.connect(dsn)


def pool(dsn: str, size: int = 4) -> ConnectionPool:
    """Connection pool for the API; each connection tunes filtered HNSW search."""

    def prepare(connection: psycopg.Connection) -> None:
        tune_hnsw(connection)
        connection.commit()

    return ConnectionPool(dsn, min_size=1, max_size=size, configure=prepare, open=True)


def tune_hnsw(connection: psycopg.Connection) -> None:
    """With a filter (repo, language), HNSW keeps scanning until it finds enough neighbours
    instead of returning a truncated list (``iterative_scan``, pgvector >= 0.8)."""
    with connection.cursor() as cursor:
        cursor.execute("SET hnsw.ef_search = 100")
        cursor.execute("SET hnsw.iterative_scan = relaxed_order")


def vector_literal(vector: list[float]) -> str:
    """pgvector literal ``[x,y,…]`` (6 decimals are plenty for a normalised vector)."""
    return "[" + ",".join(f"{x:.6f}" for x in vector) + "]"
