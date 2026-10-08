import os
import shutil
import tempfile

# Must be set BEFORE importing the app.
_TMP = tempfile.mkdtemp(prefix="certgen_test_")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["STORAGE_DIR"] = f"{_TMP}/storage"

import pytest
from fastapi.testclient import TestClient

from app.config import STORAGE_DIR
from app.database import Base, engine
from app.main import app


@pytest.fixture(autouse=True)
def clean_state():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    shutil.rmtree(STORAGE_DIR, ignore_errors=True)
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    yield


@pytest.fixture
def client():
    # TestClient runs background tasks before returning the response,
    # so a job is already finished when POST /jobs returns.
    return TestClient(app)


def make_payload(recipients=None, **extra):
    body = {
        "event_name": "PyCon Workshop 2026",
        "issuer": "Code Academy",
        "issue_date": "2026-10-01",
        "recipients": recipients
        if recipients is not None
        else [
            {"name": "Asha Rao", "email": "asha@example.com", "course": "Python Basics"},
            {"name": "Ben Carter", "email": "ben@example.com"},
        ],
    }
    body.update(extra)
    return body
