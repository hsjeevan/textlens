import asyncio
import hashlib
import json
import uuid

import pytest

from app import store
from app.flows import analyze_file_flow, run_analysis
from app.nlp_engine import analyze_text

TEXT = (
    "My bill had an extra charge and the fees keep rising! "
    "The support agent was helpful though. Coverage is great."
)


@pytest.fixture
def text_file(tmp_path):
    path = tmp_path / "input.txt"
    path.write_text(TEXT, encoding="utf-8")
    return path


def _new_run(redis_server):
    run_id = str(uuid.uuid4())
    store.create_run(redis_server, run_id, "input.txt")
    return run_id


def _run_flow(path, run_id, force=False):
    return asyncio.run(analyze_file_flow(file_path=str(path), run_id=run_id, force=force))


STEPS = ("tokens", "stats", "keywords", "tone", "themes")


def test_flow_matches_synchronous_engine(redis_server, text_file):
    run_id = _new_run(redis_server)
    assert _run_flow(text_file, run_id) == analyze_text(TEXT)


def test_flow_records_completed_status(redis_server, text_file):
    run_id = _new_run(redis_server)
    result = _run_flow(text_file, run_id)

    run = store.get_run(redis_server, run_id)
    assert run["status"] == "completed"
    assert run["result"] == result
    assert run["cache_hit"] is False
    assert run["flow_run_id"]  # Prefect's own run id, for tracing in the Prefect UI
    assert run["filename"] == "input.txt"


def test_flow_caches_intermediate_and_final_results(redis_server, text_file):
    _run_flow(text_file, _new_run(redis_server))

    digest = hashlib.sha256(TEXT.encode()).hexdigest()
    for step in ("tokens", "stats", "keywords:10", "tone", "themes"):
        assert redis_server.exists(store.step_key(digest, step)), step
    assert redis_server.exists(store.result_key(digest, 10))
    assert redis_server.ttl(store.result_key(digest, 10)) > 0


def test_repeat_content_is_served_from_cache(redis_server, text_file, tmp_path):
    first = _run_flow(text_file, _new_run(redis_server))

    # Same content under a different filename still hits the cache.
    copy = tmp_path / "copy.txt"
    copy.write_text(TEXT, encoding="utf-8")
    run_id = _new_run(redis_server)
    assert _run_flow(copy, run_id) == first
    run = store.get_run(redis_server, run_id)
    assert run["cache_hit"] is True
    assert run["cache"] == {
        "result": "cache", "steps": dict.fromkeys(STEPS, "cache"), "forced": False
    }


def test_fresh_run_reports_nlp_source(redis_server, text_file):
    run_id = _new_run(redis_server)
    _run_flow(text_file, run_id)
    assert store.get_run(redis_server, run_id)["cache"] == {
        "result": "nlp", "steps": dict.fromkeys(STEPS, "nlp"), "forced": False
    }


def test_partial_step_cache_is_reused(redis_server, text_file):
    digest = hashlib.sha256(TEXT.encode()).hexdigest()
    sentinel = {"label": "cached", "scores": {}, "indicators": {}}
    redis_server.set(store.step_key(digest, "tone"), json.dumps(sentinel))

    run_id = _new_run(redis_server)
    result = _run_flow(text_file, run_id)
    assert result["tone"] == sentinel
    steps = store.get_run(redis_server, run_id)["cache"]["steps"]
    assert steps == {**dict.fromkeys(STEPS, "nlp"), "tone": "cache"}


def test_force_skips_and_overwrites_cache(redis_server, text_file):
    _run_flow(text_file, _new_run(redis_server))
    digest = hashlib.sha256(TEXT.encode()).hexdigest()
    sentinel = {"label": "stale", "scores": {}, "indicators": {}}
    redis_server.set(store.step_key(digest, "tone"), json.dumps(sentinel))

    run_id = _new_run(redis_server)
    result = _run_flow(text_file, run_id, force=True)

    assert result == analyze_text(TEXT)
    run = store.get_run(redis_server, run_id)
    assert run["cache_hit"] is False
    assert run["cache"] == {
        "result": "nlp", "steps": dict.fromkeys(STEPS, "nlp"), "forced": True
    }
    # The stale step was replaced with the fresh value.
    assert json.loads(redis_server.get(store.step_key(digest, "tone"))) == result["tone"]


def test_flow_failure_is_recorded(redis_server, tmp_path):
    run_id = _new_run(redis_server)
    with pytest.raises(FileNotFoundError):
        _run_flow(tmp_path / "missing.txt", run_id)

    run = store.get_run(redis_server, run_id)
    assert run["status"] == "failed"
    assert "FileNotFoundError" in run["error"]


def test_run_analysis_deletes_file_and_swallows_errors(redis_server, text_file, tmp_path):
    run_id = _new_run(redis_server)
    run_analysis(str(text_file), run_id)
    assert not text_file.exists()
    assert store.get_run(redis_server, run_id)["status"] == "completed"

    # A failing run must not raise out of the background worker.
    run_analysis(str(tmp_path / "missing.txt"), _new_run(redis_server))
