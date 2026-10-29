"""Shared test setup: a throwaway account database and a fresh signed-in client per test."""
import os
import sys
import tempfile
import uuid

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["MOMO_DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="momo-test-"), "test.db")
os.chdir(ROOT)

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402

PASSWORD = "Ledger-check-42"


@pytest.fixture(autouse=True)
def fresh_rate_limits():
    """Every test client shares one address; start each test with empty rate-limit counters."""
    from backend import auth
    auth._fails.clear()
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def new_user(c, name="Kwame Boateng"):
    email = f"user-{uuid.uuid4().hex[:10]}@example.org"
    r = c.post("/api/auth/register", json={"name": name, "email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return email


@pytest.fixture
def signed_in(client):
    client.email = new_user(client)
    return client
