from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env.vscode")


def normalize_database_url(raw: str) -> str:
    url = make_url(raw)
    driver = url.drivername
    if driver == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    elif driver == "mysql":
        url = url.set(drivername="mysql+pymysql")
    return url.render_as_string(hide_password=False)


raw_url = os.getenv("CCTV_DATABASE_URL") or os.getenv("DATABASE_URL") or "sqlite:///./cctv_report.db"
url = make_url(raw_url)
if url.drivername.startswith("sqlite") and url.database not in (None, "", ":memory:"):
    database_path = Path(url.database)
    if not database_path.is_absolute():
        url = url.set(database=str((PROJECT_ROOT / database_path).resolve()))
DATABASE_URL = normalize_database_url(url.render_as_string(hide_password=False))
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
