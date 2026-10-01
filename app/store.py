"""Redis-backed storage for run status and cached NLP results.

Key layout (all under ``PREFIX``):
  run:{run_id}             hash   -- status record for one upload/flow run
  step:{digest}:{step}     string -- JSON of one intermediate NLP step
  result:{digest}:{top_n}  string -- JSON of the final insights payload

``digest`` is the SHA-256 of the file's text, so identical uploads share cached
steps and results regardless of filename.

Hash fields are stored JSON-encoded so non-string values (result dicts, bools)
round-trip without per-field special cases.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from enum import StrEnum
from functools import lru_cache
from typing import Any

import redis
import redis.asyncio as aioredis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CACHE_TTL_SECONDS = int(os.getenv("TEXTLENS_CACHE_TTL_SECONDS", str(7 * 24 * 3600)))
RUN_TTL_SECONDS = int(os.getenv("TEXTLENS_RUN_TTL_SECONDS", str(24 * 3600)))
# Bump the version to invalidate cached results after changing NLP logic.
PREFIX = "textlens:v1"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@lru_cache(maxsize=1)
def get_sync_client() -> redis.Redis:
    """Shared client for the API process (connection-pooled, thread-safe)."""
    return redis.Redis.from_url(REDIS_URL, decode_responses=True)


def get_async_client() -> aioredis.Redis:
    """New async client; async clients are bound to the event loop that uses them,
    so each flow run creates (and closes) its own."""
    return aioredis.Redis.from_url(REDIS_URL, decode_responses=True)


def run_key(run_id: str) -> str:
    return f"{PREFIX}:run:{run_id}"


def step_key(digest: str, step: str) -> str:
    return f"{PREFIX}:step:{digest}:{step}"


def result_key(digest: str, top_n: int) -> str:
    return f"{PREFIX}:result:{digest}:{top_n}"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _encode(fields: dict[str, Any]) -> dict[str, str]:
    return {k: json.dumps(v) for k, v in {**fields, "updated_at": _now()}.items()}


# --- Run status (sync: used by the API) --------------------------------------

def create_run(r: redis.Redis, run_id: str, filename: str | None) -> None:
    fields = {"status": RunStatus.PENDING, "filename": filename, "created_at": _now()}
    with r.pipeline() as pipe:
        pipe.hset(run_key(run_id), mapping=_encode(fields))
        pipe.expire(run_key(run_id), RUN_TTL_SECONDS)
        pipe.execute()


def get_run(r: redis.Redis, run_id: str) -> dict[str, Any] | None:
    raw = r.hgetall(run_key(run_id))
    if not raw:
        return None
    return {k: json.loads(v) for k, v in raw.items()}


# --- Run status + caching (async: used inside the Prefect flow) ---------------

async def aupdate_run(r: aioredis.Redis, run_id: str, **fields: Any) -> None:
    async with r.pipeline() as pipe:
        pipe.hset(run_key(run_id), mapping=_encode(fields))
        pipe.expire(run_key(run_id), RUN_TTL_SECONDS)
        await pipe.execute()


async def aget_json(r: aioredis.Redis, key: str) -> Any | None:
    raw = await r.get(key)
    return None if raw is None else json.loads(raw)


async def aset_json(r: aioredis.Redis, key: str, value: Any, ttl: int = CACHE_TTL_SECONDS) -> None:
    await r.set(key, json.dumps(value), ex=ttl)
