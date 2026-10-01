"""Prefect flow that analyses an uploaded text file and caches results in Redis.

Pipeline:
  read file -> tokenize -> (stats | keywords | tone | themes, concurrently) -> assemble

Each NLP step's output is cached in Redis by content hash, and so is the final
payload; a repeat upload of the same text is served straight from the cache
(unless `force` is set, which recomputes everything and overwrites the cache).
The run record's `cache` field says which parts came from the cache vs the NLP
pipeline.
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
    force: bool = False,
) -> tuple[Any, str]:
    """Return (output, source) for `step`: the cached value with source "cache", or
    a fresh task result (written back to the cache) with source "nlp".

    With `force`, the cache is not read but is still overwritten.
    """
    key = store.step_key(digest, step)
    if not force:
        cached = await store.aget_json(r, key)
        if cached is not None:
            get_run_logger().info("Cache hit for step %r", step)
            return cached, "cache"
    value = await task_fn(*args)
    await store.aset_json(r, key, value)
    return value, "nlp"


STEP_NAMES = ("tokens", "stats", "keywords", "tone", "themes")


@flow(name="textlens-analysis")
async def analyze_file_flow(
    file_path: str, run_id: str, top_n: int = nlp_engine.TOP_KEYWORDS, force: bool = False
) -> dict[str, Any]:
    logger = get_run_logger()
    r = store.get_async_client()
    try:
        await store.aupdate_run(r, run_id, status=RunStatus.RUNNING, flow_run_id=flow_run.id)

        text = await read_text_file(file_path)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        result_key = store.result_key(digest, top_n)

        result = None if force else await store.aget_json(r, result_key)
        cache_hit = result is not None
        if cache_hit:
            logger.info("Final result cache hit for digest %s", digest[:12])
            steps = dict.fromkeys(STEP_NAMES, "cache")
        else:
            if force:
                logger.info("Cache bypassed (force) for digest %s", digest[:12])
            tokens, tokens_src = await _cached_step(
                r, digest, "tokens", tokenize, text, force=force
            )
            words = tokens["words"]
            (stats, stats_src), (keywords, kw_src), (tone, tone_src), (themes, themes_src) = (
                await asyncio.gather(
                    _cached_step(r, digest, "stats", count_stats, tokens, force=force),
                    _cached_step(r, digest, f"keywords:{top_n}", extract_keywords,
                                 words, top_n, force=force),
                    _cached_step(r, digest, "tone", analyze_tone, text, words, force=force),
                    _cached_step(r, digest, "themes", detect_themes, words, force=force),
                )
            )
            result = {**stats, "top_keywords": keywords, "tone": tone, "themes": themes}
            await store.aset_json(r, result_key, result)
            steps = {"tokens": tokens_src, "stats": stats_src, "keywords": kw_src,
                     "tone": tone_src, "themes": themes_src}

        cache = {"result": "cache" if cache_hit else "nlp", "steps": steps, "forced": force}
        await store.aupdate_run(
            r, run_id, status=RunStatus.COMPLETED, result=result, cache_hit=cache_hit,
            cache=cache,
        )
        return result
    except Exception as exc:
        await store.aupdate_run(
            r, run_id, status=RunStatus.FAILED, error=f"{type(exc).__name__}: {exc}"
        )
        raise
    finally:
        await r.aclose()


def run_analysis(file_path: str, run_id: str, force: bool = False) -> None:
    """Blocking entry point for running the flow off the API's event loop.

    Always deletes the uploaded file afterwards. Failures are already recorded
    in the run status by the flow, so they are only logged here.
    """
    try:
        asyncio.run(analyze_file_flow(file_path=file_path, run_id=run_id, force=force))
    except Exception:
        log.exception("NLP flow failed for run %s", run_id)
    finally:
        Path(file_path).unlink(missing_ok=True)
