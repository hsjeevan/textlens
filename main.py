"""FastAPI entry point for the TextLens service.

Run with:  uvicorn main:app --reload
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path, PurePath
from typing import Any

import redis
from fastapi import FastAPI, File, HTTPException, Request, UploadFile, status

from app import store
from app.flows import run_analysis
from app.nlp_engine import ensure_nltk_resources
from app.store import RunStatus

log = logging.getLogger(__name__)

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "uploads"))
# Flow runs execute on a dedicated pool so long analyses never tie up the
# threadpool FastAPI uses to serve sync endpoints.
MAX_CONCURRENT_RUNS = int(os.getenv("TEXTLENS_MAX_CONCURRENT_RUNS", "4"))
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
ALLOWED_EXTENSIONS = {".txt"}
# Browsers and clients often send plain-text files as octet-stream, so accept it
# and rely on the extension + UTF-8 decode check instead.
ALLOWED_CONTENT_TYPES = {"text/plain", "application/octet-stream", ""}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Fetch NLTK data once at startup rather than on the first request.
    ensure_nltk_resources()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    app.state.executor = ThreadPoolExecutor(
        max_workers=MAX_CONCURRENT_RUNS, thread_name_prefix="textlens-flow"
    )
    try:
        yield
    finally:
        # Let in-flight runs finish; queued-but-unstarted runs are dropped and
        # will remain "pending" until their status record expires.
        app.state.executor.shutdown(wait=True, cancel_futures=True)


app = FastAPI(title="TextLens", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _read_text(file: UploadFile) -> str:
    extension = PurePath(file.filename or "").suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Only .txt files are supported (got {extension or 'no extension'!r}).",
        )

    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported content type {content_type!r}; expected text/plain.",
        )

    # Read one byte past the limit so oversized files are detected without
    # loading them entirely into memory.
    raw = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
        )

    # A NUL byte almost always means a binary file renamed to .txt.
    if b"\x00" in raw:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="File appears to be binary, not plain text.",
        )

    try:
        # utf-8-sig also strips a leading BOM (common in Windows-saved files).
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File is not valid UTF-8 text.",
        )


def _redis_unavailable(exc: redis.RedisError) -> HTTPException:
    log.error("Redis error: %s", exc)
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Result store is unavailable; try again shortly.",
    )


@app.post("/upload", status_code=status.HTTP_202_ACCEPTED)
def upload(request: Request, file: UploadFile = File(...)) -> dict[str, Any]:
    """Validate and store the file, then start the Prefect flow in the background."""
    try:
        text = _read_text(file)
    finally:
        file.file.close()

    run_id = str(uuid.uuid4())
    # Written back as UTF-8 so the flow never has to re-validate the encoding.
    path = UPLOAD_DIR / f"{run_id}.txt"
    path.write_text(text, encoding="utf-8")

    try:
        store.create_run(store.get_sync_client(), run_id, file.filename)
    except redis.RedisError as exc:
        path.unlink(missing_ok=True)
        raise _redis_unavailable(exc)

    request.app.state.executor.submit(run_analysis, str(path), run_id)

    return {
        "run_id": run_id,
        "status": RunStatus.PENDING,
        "status_url": request.app.url_path_for("get_insights", run_id=run_id),
    }


@app.get("/insights/{run_id}")
def get_insights(run_id: uuid.UUID) -> dict[str, Any]:
    """Report a run's status; includes `result` once completed or `error` if failed."""
    try:
        run = store.get_run(store.get_sync_client(), str(run_id))
    except redis.RedisError as exc:
        raise _redis_unavailable(exc)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unknown run_id (it may have expired).",
        )
    return {"run_id": str(run_id), **run}
