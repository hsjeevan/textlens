import time
import uuid

import pytest
import redis
from fastapi.testclient import TestClient

import main
from app import store
from main import app


@pytest.fixture
def client(redis_server, tmp_path, monkeypatch):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path / "uploads")
    with TestClient(app) as c:
        yield c


def _upload(client, name, content, content_type="text/plain"):
    return client.post("/upload", files={"file": (name, content, content_type)})


def _wait_for(client, run_id, timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/insights/{run_id}").json()
        if body["status"] in ("completed", "failed"):
            return body
        time.sleep(0.1)
    pytest.fail(f"run {run_id} did not finish within {timeout}s")


def test_upload_returns_run_id_immediately(client):
    resp = _upload(client, "review.txt", b"Hello there.")
    assert resp.status_code == 202
    body = resp.json()
    uuid.UUID(body["run_id"])
    assert body["status"] == "pending"
    assert body["status_url"] == f"/insights/{body['run_id']}"


def test_upload_then_poll_for_insights(client):
    text = b"My bill had an extra charge. I want a refund! The support was awful."
    run_id = _upload(client, "review.txt", text).json()["run_id"]

    body = _wait_for(client, run_id)
    assert body["status"] == "completed"
    assert body["filename"] == "review.txt"
    insights = body["result"]
    assert insights["sentence_count"] == 3
    assert insights["tone"]["label"] == "negative"
    assert "billing_pricing" in insights["themes"]["dominant"]


def test_uploaded_file_is_removed_after_processing(client):
    run_id = _upload(client, "a.txt", b"Some text here.").json()["run_id"]
    _wait_for(client, run_id)
    # Cleanup runs just after the flow marks the run completed, so allow a moment.
    deadline = time.monotonic() + 5
    while any(main.UPLOAD_DIR.iterdir()) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert list(main.UPLOAD_DIR.iterdir()) == []


def test_accepts_octet_stream_and_bom(client):
    run_id = _upload(client, "notes.TXT", "﻿Hello there.".encode(),
                     "application/octet-stream").json()["run_id"]
    assert _wait_for(client, run_id)["result"]["word_count"] == 2


def test_empty_file_completes_with_empty_insights(client):
    run_id = _upload(client, "empty.txt", b"").json()["run_id"]
    body = _wait_for(client, run_id)
    assert body["status"] == "completed"
    assert body["result"]["word_count"] == 0


def test_force_upload_skips_cache(client):
    text = b"Same text twice."
    _wait_for(client, _upload(client, "a.txt", text).json()["run_id"])

    resp = client.post("/upload?force=true", files={"file": ("a.txt", text, "text/plain")})
    assert resp.json()["force"] is True
    body = _wait_for(client, resp.json()["run_id"])
    assert body["cache_hit"] is False
    assert body["cache"]["forced"] is True
    assert set(body["cache"]["steps"].values()) == {"nlp"}


def test_clear_cache_removes_cached_results_but_keeps_runs(client, redis_server):
    run_id = _upload(client, "a.txt", b"Cache me please.").json()["run_id"]
    _wait_for(client, run_id)
    assert redis_server.keys(f"{store.PREFIX}:result:*")

    resp = client.delete("/cache")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 6  # 5 steps + final result
    assert redis_server.keys(f"{store.PREFIX}:step:*") == []
    assert redis_server.keys(f"{store.PREFIX}:result:*") == []
    assert client.get(f"/insights/{run_id}").status_code == 200

    # The next upload of the same text is computed afresh.
    body = _wait_for(client, _upload(client, "a.txt", b"Cache me please.").json()["run_id"])
    assert body["cache"]["result"] == "nlp"
    assert client.delete("/cache").json()["deleted"] == 6


def test_unknown_run_id_is_404(client):
    assert client.get(f"/insights/{uuid.uuid4()}").status_code == 404


def test_malformed_run_id_is_422(client):
    assert client.get("/insights/not-a-uuid").status_code == 422


def test_redis_down_returns_503(client, monkeypatch, tmp_path):
    dead = redis.Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.2)
    monkeypatch.setattr(store, "get_sync_client", lambda: dead)
    assert _upload(client, "a.txt", b"text").status_code == 503
    assert list(main.UPLOAD_DIR.iterdir()) == []  # no orphaned upload
    assert client.get(f"/insights/{uuid.uuid4()}").status_code == 503
    assert client.delete("/cache").status_code == 503


# --- Validation happens synchronously, before any flow is started ------------

@pytest.mark.parametrize("name", ["report.pdf", "image.png", "noextension"])
def test_rejects_wrong_extension(client, name):
    resp = _upload(client, name, b"some text")
    assert resp.status_code == 415
    assert "Only .txt" in resp.json()["detail"]


def test_rejects_wrong_content_type(client):
    assert _upload(client, "fake.txt", b"text", "application/pdf").status_code == 415


def test_rejects_binary_content(client):
    resp = _upload(client, "data.txt", b"\x89PNG\r\n\x1a\n\x00\x00\x00")
    assert resp.status_code == 415
    assert "binary" in resp.json()["detail"]


def test_rejects_non_utf8(client):
    assert _upload(client, "latin.txt", "café".encode("latin-1")).status_code == 400


def test_rejects_oversized_file(client, monkeypatch):
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 10)
    assert _upload(client, "big.txt", b"x" * 11).status_code == 413


def test_missing_file_field(client):
    assert client.post("/upload").status_code == 422


def test_rejected_upload_creates_no_run_or_file(client, redis_server):
    _upload(client, "report.pdf", b"text")
    assert redis_server.keys("*") == []
    assert list(main.UPLOAD_DIR.iterdir()) == []
