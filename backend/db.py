"""Local PostgreSQL access: pool, schema bootstrap, and analysis history queries."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import asyncpg

_pool: asyncpg.Pool | None = None


class DatabaseError(Exception):
    def __init__(self, message: str, code: str = "DATABASE_ERROR", status_code: int = 503):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


def database_url() -> str:
    url = (os.getenv("DATABASE_URL") or "").strip()
    if not url:
        raise DatabaseError(
            "DATABASE_URL is not set. Add it to .env (local PostgreSQL via Docker Desktop)."
        )
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise DatabaseError("Database pool is not initialized.")
    return _pool


async def init_db() -> None:
    global _pool
    try:
        _pool = await asyncpg.create_pool(dsn=database_url(), min_size=1, max_size=10)
    except Exception as exc:
        raise DatabaseError(
            f"Unable to connect to PostgreSQL. Is Docker Desktop Postgres running? {exc}"
        ) from exc

    async with _pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id UUID PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS analyses (
                id UUID PRIMARY KEY,
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                region TEXT NOT NULL,
                resources_scanned INTEGER NOT NULL DEFAULT 0,
                issues_found INTEGER NOT NULL DEFAULT 0,
                estimated_savings TEXT,
                analysis_result JSONB,
                status TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS analyses_user_id_created_at_idx "
            "ON analyses (user_id, created_at DESC)"
        )


async def close_db() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def ping_db() -> bool:
    try:
        async with get_pool().acquire() as conn:
            value = await conn.fetchval("SELECT 1")
        return value == 1
    except Exception:
        return False


def _user_row(row: asyncpg.Record) -> dict[str, Any]:
    created_at = row["created_at"]
    return {
        "id": row["id"],
        "email": row["email"],
        "password_hash": row["password_hash"],
        "created_at": created_at.isoformat() if created_at else None,
    }


async def get_user_by_email(email: str) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, email, password_hash, created_at FROM users WHERE email = $1",
            email,
        )
    return _user_row(row) if row else None


async def get_user_by_id(user_id: UUID) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, email, password_hash, created_at FROM users WHERE id = $1",
            user_id,
        )
    return _user_row(row) if row else None


async def create_user(*, email: str, password_hash: str) -> dict[str, Any]:
    user_id = uuid4()
    created_at = datetime.now(timezone.utc)
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO users (id, email, password_hash, created_at)
                VALUES ($1, $2, $3, $4)
                """,
                user_id,
                email,
                password_hash,
                created_at,
            )
    except asyncpg.UniqueViolationError as exc:
        raise DatabaseError(
            "An account with this email already exists.",
            code="EMAIL_TAKEN",
            status_code=409,
        ) from exc
    return {
        "id": user_id,
        "email": email,
        "password_hash": password_hash,
        "created_at": created_at.isoformat(),
    }


async def get_analysis_for_user(user_id: UUID, analysis_id: UUID) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, user_id, region, resources_scanned, issues_found,
                   estimated_savings, analysis_result, status, created_at
            FROM analyses
            WHERE id = $1 AND user_id = $2
            """,
            analysis_id,
            user_id,
        )
    return _row_to_analysis(row) if row else None


async def insert_analysis(
    *,
    analysis_id: UUID,
    user_id: UUID,
    region: str,
    status: str,
) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO analyses (
                id, user_id, region, resources_scanned, issues_found,
                estimated_savings, analysis_result, status, created_at
            )
            VALUES ($1, $2, $3, 0, 0, NULL, NULL, $4, $5)
            """,
            analysis_id,
            user_id,
            region,
            status,
            datetime.now(timezone.utc),
        )


async def update_analysis(
    *,
    analysis_id: UUID,
    status: str,
    resources_scanned: int = 0,
    issues_found: int = 0,
    estimated_savings: str | None = None,
    analysis_result: dict[str, Any] | None = None,
) -> None:
    payload = json.dumps(analysis_result, default=str) if analysis_result is not None else None
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE analyses
            SET status = $2,
                resources_scanned = $3,
                issues_found = $4,
                estimated_savings = $5,
                analysis_result = $6::jsonb
            WHERE id = $1
            """,
            analysis_id,
            status,
            resources_scanned,
            issues_found,
            estimated_savings,
            payload,
        )


def _row_to_analysis(row: asyncpg.Record) -> dict[str, Any]:
    result = row["analysis_result"]
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            result = {"raw": result}

    created_at = row["created_at"]
    return {
        "id": str(row["id"]),
        "user_id": str(row["user_id"]),
        "region": row["region"],
        "resources_scanned": row["resources_scanned"],
        "issues_found": row["issues_found"],
        "estimated_savings": row["estimated_savings"],
        "analysis_result": result,
        "status": row["status"],
        "created_at": created_at.isoformat() if created_at else None,
    }


async def list_analyses_for_user(user_id: UUID, limit: int = 50) -> list[dict[str, Any]]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, user_id, region, resources_scanned, issues_found,
                   estimated_savings, analysis_result, status, created_at
            FROM analyses
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            user_id,
            limit,
        )
    return [_row_to_analysis(row) for row in rows]
