"""Prefect flow that analyses an uploaded text file and caches results in Redis.

Pipeline:
  read file -> tokenize -> (stats | keywords | tone | themes, concurrently) -> assemble

Each NLP step's output is cached in Redis by content hash, and so is the final
payload; a repeat upload of the same text is served straight from the cache.
Run status is written to Redis as the flow progresses so the API can report it.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

from prefect import flow, task
from prefect.cache_policies import NONE
from prefect.logging import get_run_logger
from prefect.runtime import flow_run

from app import nlp_engine, store
from app.store import RunStatus

log = logging.getLogger(__name__)

# Caching is handled explicitly in Redis, so Prefect's own input-hash caching is
# disabled (it would also try to hash unhashable arguments).
_task = task(cache_policy=NONE)


# The NLP functions are CPU-bound and synchronous; running them via
# asyncio.to_thread keeps the flow's event loop free so the independent steps
# below can run concurrently.

@_task
async def read_text_file(path: str) -> str:
    return await asyncio.to_thread(Path(path).read_text, encoding="utf-8-sig")


@_task
async def tokenize(text: str) -> dict[str, list[str]]:
    return await asyncio.to_thread(nlp_engine.tokenize, text)


@_task
async def count_stats(tokens: dict[str, list[str]]) -> dict[str, int]:
    return nlp_engine.count_stats(tokens)


@_task
async def extract_keywords(words: list[str], top_n: int) -> list[dict[str, Any]]:
    return await asyncio.to_thread(nlp_engine.extract_keywords, words, top_n)


@_task
async def analyze_tone(text: str, words: list[str]) -> dict[str, Any]:
    return await asyncio.to_thread(nlp_engine.analyze_tone, text, words)


@_task
async def detect_themes(words: list[str]) -> dict[str, Any]:
    return await asyncio.to_thread(nlp_engine.detect_themes, words)


async def _cached_step(
    r: store.aioredis.Redis,
    digest: str,
    step: str,
    task_fn: Callable[..., Awaitable[Any]],
    *args: Any,
) -> Any:
    """Return the cached output of `step` for this text, or run the task and cache it."""
    key = store.step_key(digest, step)
    cached = await store.aget_json(r, key)
    if cached is not None:
        get_run_logger().info("Cache hit for step %r", step)
        return cached
    value = await task_fn(*args)
    await store.aset_json(r, key, value)
    return value


@flow(name="textlens-analysis")
async def analyze_file_flow(
    file_path: str, run_id: str, top_n: int = nlp_engine.TOP_KEYWORDS
) -> dict[str, Any]:
    logger = get_run_logger()
    r = store.get_async_client()
    try:
        await store.aupdate_run(r, run_id, status=RunStatus.RUNNING, flow_run_id=flow_run.id)

        text = await read_text_file(file_path)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        result_key = store.result_key(digest, top_n)

        result = await store.aget_json(r, result_key)
        cache_hit = result is not None
        if cache_hit:
            logger.info("Final result cache hit for digest %s", digest[:12])
        else:
            tokens = await _cached_step(r, digest, "tokens", tokenize, text)
            words = tokens["words"]
            stats, keywords, tone, themes = await asyncio.gather(
                _cached_step(r, digest, "stats", count_stats, tokens),
                _cached_step(r, digest, f"keywords:{top_n}", extract_keywords, words, top_n),
                _cached_step(r, digest, "tone", analyze_tone, text, words),
                _cached_step(r, digest, "themes", detect_themes, words),
            )
            result = {**stats, "top_keywords": keywords, "tone": tone, "themes": themes}
            await store.aset_json(r, result_key, result)

        await store.aupdate_run(
            r, run_id, status=RunStatus.COMPLETED, result=result, cache_hit=cache_hit
        )
        return result
    except Exception as exc:
        await store.aupdate_run(
            r, run_id, status=RunStatus.FAILED, error=f"{type(exc).__name__}: {exc}"
        )
        raise
    finally:
        await r.aclose()


def run_analysis(file_path: str, run_id: str) -> None:
    """Blocking entry point for running the flow off the API's event loop.

    Always deletes the uploaded file afterwards. Failures are already recorded
    in the run status by the flow, so they are only logged here.
    """
    try:
        asyncio.run(analyze_file_flow(file_path=file_path, run_id=run_id))
    except Exception:
        log.exception("NLP flow failed for run %s", run_id)
    finally:
        Path(file_path).unlink(missing_ok=True)
