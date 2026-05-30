from __future__ import annotations

from .services import clients # noqa: F401
 
import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker, declarative_base

# Default: local SQLite i projektroten (enkel start).

#ändrad under lab2
#DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")

DATABASE_URL = "sqlite:///./app.db"


connect_args = {}

if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, echo=False, future=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: ger en DB-session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
		
Base = declarative_base()
