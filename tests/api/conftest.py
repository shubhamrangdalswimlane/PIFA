"""API tests against a real PostgreSQL (TEST_DATABASE_URL) with Keycloak and Drools replaced by fakes."""

import os

os.environ.setdefault("DATABASE_URL", os.environ.get("TEST_DATABASE_URL", "postgresql://pifa:pifa@localhost:5433/pifa_test"))
os.environ["AUTO_MIGRATE"] = "true"

import psycopg  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from pifa_api import clients, db  # noqa: E402
from pifa_api.auth import User, current_user  # noqa: E402
from pifa_api.config import get_settings  # noqa: E402
from pifa_api.domain import REGIONS  # noqa: E402
from pifa_api.main import app  # noqa: E402

from .fake_rules import fake_rules  # noqa: E402


def make_user(username: str) -> User:
    role_by_prefix = {"sm": "SALES_MANAGER", "rm": "REGIONAL_MANAGER"}
    if "." in username:
        prefix, region = username.split(".")
        return User(username, username, role_by_prefix[prefix], region.title(), {"preferred_username": username})
    role = {"planner": "PLANNER", "head": "HEAD_OF_SALES", "admin": "ADMIN"}[username]
    return User(username, username, role, None, {"preferred_username": username})


@pytest.fixture()
def fresh_db():
    with psycopg.connect(get_settings().database_url, autocommit=True) as c:
        c.execute("DROP SCHEMA IF EXISTS pifa CASCADE")
    db._migrated = False
    yield


@pytest.fixture()
def api(fresh_db, monkeypatch):
    monkeypatch.setattr(clients, "rules", fake_rules)
    monkeypatch.setattr(clients, "export_file", lambda *a, **k: b"PK\x03\x04fake")
    state = {"user": None}
    app.dependency_overrides[current_user] = lambda: state["user"]

    class Api:
        def __init__(self):
            self.client = TestClient(app)

        def as_(self, username: str) -> "Api":
            state["user"] = make_user(username)
            return self

        def __getattr__(self, method):
            return getattr(self.client, method)

    yield Api()
    app.dependency_overrides.clear()


@pytest.fixture()
def regions():
    return REGIONS
