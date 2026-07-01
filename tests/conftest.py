"""pytest fixtures — test database is ALWAYS isolated from production.

DB_PATH is set BEFORE any backend import so config.py picks up the temp path.
"""

import gc
import os
import tempfile
import time
from pathlib import Path

# ═════════════════════════════════════════════════════════════
# CRITICAL: must set all required env vars before importing anything from backend.
# config.py / database.py / main.py enforce these at import time.
# ═════════════════════════════════════════════════════════════
_TEST_DB = Path(tempfile.gettempdir()) / "stockai_test.db"
os.environ.setdefault("DB_PATH", str(_TEST_DB))
os.environ.setdefault("JWT_SECRET", "pytest-jwt-secret-key-32-bytes-ok")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password-123")
os.environ.setdefault("ADMIN_EMAIL", "admin@stockai.com")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3001")

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import pytest
from fastapi.testclient import TestClient


def _build_auth_client(client, app):
    """Login against the test database's admin user and return an authenticated client."""
    # ensure_admin_user() runs once per test session (see session-scoped fixture).
    # The admin password comes from ADMIN_PASSWORD env var; tests use the real one.
    from config import ADMIN_PASSWORD
    resp = client.post("/api/auth/login", json={
        "email": "admin@stockai.com",
        "password": ADMIN_PASSWORD,
    })
    if resp.status_code == 200:
        token = resp.json()["token"]
        return _AuthClient(client, token)
    # Let 401s surface rather than crashing the fixture
    return client


def _drain_connection_pool():
    """Close pooled SQLite connections so the temp DB can be deleted on Windows."""
    try:
        from database import _conn_pool
    except Exception:
        return

    while True:
        try:
            conn = _conn_pool.get_nowait()
        except Exception:
            break
        try:
            conn.close()
        except Exception:
            pass


@pytest.fixture(scope="session")
def _test_db_session():
    """Create a fresh test database once per test session."""
    # Delete stale test db from previous run (if any)
    if _TEST_DB.exists():
        try:
            _TEST_DB.unlink()
        except PermissionError:
            time.sleep(0.3)
            _TEST_DB.unlink(missing_ok=True)

    from database import init_db, ensure_admin_user
    init_db()
    ensure_admin_user()

    yield _TEST_DB

    _drain_connection_pool()
    gc.collect()

    # Cleanup (Windows may hold file handles briefly after conn.close())
    if _TEST_DB.exists():
        for attempt in range(5):
            try:
                _TEST_DB.unlink()
                break
            except PermissionError:
                if attempt < 4:
                    time.sleep(0.2)
                    gc.collect()
                    _drain_connection_pool()
                else:
                    pass


@pytest.fixture
def client(_test_db_session):
    """TestClient with JWT auth — isolated test database."""
    from main import app

    with TestClient(app) as c:
        yield _build_auth_client(c, app)


@pytest.fixture
def db(_test_db_session):
    """Raw database connection to the test database."""
    from database import get_db

    conn = get_db()
    try:
        yield conn
    finally:
        conn.close()


# ═════════════════════════════════════════════════════════════
# Authenticated client wrapper
# ═════════════════════════════════════════════════════════════

class _AuthClient:
    """Wrap TestClient to auto-attach JWT Bearer token on every request."""

    def __init__(self, client, token):
        self._client = client
        self._token = token

    def _headers(self, extra=None):
        h = {"Authorization": f"Bearer {self._token}"}
        if extra:
            h.update(extra)
        return h

    def get(self, url, **kwargs):
        kwargs["headers"] = self._headers(kwargs.get("headers"))
        return self._client.get(url, **kwargs)

    def post(self, url, **kwargs):
        kwargs["headers"] = self._headers(kwargs.get("headers"))
        return self._client.post(url, **kwargs)

    def put(self, url, **kwargs):
        kwargs["headers"] = self._headers(kwargs.get("headers"))
        return self._client.put(url, **kwargs)

    def delete(self, url, **kwargs):
        kwargs["headers"] = self._headers(kwargs.get("headers"))
        return self._client.delete(url, **kwargs)

    def patch(self, url, **kwargs):
        kwargs["headers"] = self._headers(kwargs.get("headers"))
        return self._client.patch(url, **kwargs)

    def __getattr__(self, name):
        return getattr(self._client, name)
