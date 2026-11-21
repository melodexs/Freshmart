import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_FILE", str(tmp_path / "db.json"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("STORE_STAFF_KEY", raising=False)
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    for m in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[m]
    from fastapi.testclient import TestClient

    from app import ratelimit
    from app.main import app

    ratelimit.reset()
    with TestClient(app) as c:
        # Pay-before-delivery needs a real bank account, so most tests start with one set.
        import asyncio

        from app import db

        asyncio.new_event_loop().run_until_complete(
            db.set_setting(
                "bank_details",
                {"bank": "Test Bank", "accountName": "OGS Test", "accountNumber": "0123456789"},
            )
        )
        yield c
