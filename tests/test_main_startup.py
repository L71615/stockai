import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from main import PUBLIC_APIS


def test_public_apis_keeps_minimal_surface():
    assert "/api/health" in PUBLIC_APIS
    assert "/api/auth/login" in PUBLIC_APIS
    assert "/api/stocks/indices/global" not in PUBLIC_APIS
