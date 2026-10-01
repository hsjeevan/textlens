import fakeredis
import pytest
from prefect.testing.utilities import prefect_test_harness

from app import store
from app.nlp_engine import ensure_nltk_resources


@pytest.fixture(scope="session", autouse=True)
def nltk_data():
    ensure_nltk_resources()


@pytest.fixture(scope="session", autouse=True)
def prefect_backend():
    # Isolated temporary Prefect API + database for the whole test session.
    with prefect_test_harness():
        yield


@pytest.fixture
def redis_server(monkeypatch):
    """In-memory Redis shared by the API's sync client and the flow's async clients."""
    server = fakeredis.FakeServer()
    sync_client = fakeredis.FakeRedis(server=server, decode_responses=True)
    monkeypatch.setattr(store, "get_sync_client", lambda: sync_client)
    monkeypatch.setattr(
        store,
        "get_async_client",
        lambda: fakeredis.FakeAsyncRedis(server=server, decode_responses=True),
    )
    return sync_client
