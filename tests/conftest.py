import sys
from pathlib import Path

# Add backend/ to sys.path so imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import app
    from database import init_db

    init_db()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db():
    from database import init_db, get_db

    init_db()
    conn = get_db()
    try:
        yield conn
    finally:
        conn.close()
