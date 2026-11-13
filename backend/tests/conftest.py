from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import current_user
from app.database import get_db
from app.main import app
from app.models import Base, Company, User

TEST_ENGINE = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSession = sessionmaker(bind=TEST_ENGINE, autoflush=False, expire_on_commit=False)


@pytest.fixture
def db() -> Generator[Session, None, None]:
    Base.metadata.create_all(TEST_ENGINE)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(TEST_ENGINE)


@pytest.fixture
def identities(db: Session):
    company = Company(company_name="Test Works Ltd", default_report_language="en")
    db.add(company)
    db.flush()
    admin = User(company_id=company.id, full_name="Test Admin", email=f"admin-{uuid4()}@example.test", role="ADMIN", is_active=True)
    viewer = User(company_id=company.id, full_name="Test Viewer", email=f"viewer-{uuid4()}@example.test", role="VIEWER", is_active=True)
    db.add_all([admin, viewer])
    db.commit()
    return {"company": company, "admin": admin, "viewer": viewer}


@pytest.fixture
def client(db: Session, identities, monkeypatch, tmp_path):
    monkeypatch.setenv("CCTV_AUTH_MODE", "manus")
    monkeypatch.setenv("ASSET_STORAGE_DIR", str(tmp_path / "assets"))
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[current_user] = lambda: identities["admin"]
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
