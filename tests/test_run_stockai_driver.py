import importlib.util
from pathlib import Path


def _load_driver_module(monkeypatch):
    driver_path = Path(r"D:/stocks/.claude/skills/run-stockai/driver.py")
    spec = importlib.util.spec_from_file_location("run_stockai_driver", driver_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_driver_login_uses_env_password(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", "admin@stockai.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "real-password")

    module = _load_driver_module(monkeypatch)

    captured = {}

    def fake_urlopen(req, timeout=10):
        captured["body"] = req.data.decode()
        class _Resp:
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc, tb):
                return False
            def read(self):
                return b'{"token":"abc"}'
        return _Resp()

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    module.login()

    assert '"password": "real-password"' in captured["body"]
