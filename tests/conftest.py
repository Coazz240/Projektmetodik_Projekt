from __future__ import annotations

import datetime as dt
from typing import Iterator

import pytest

from fastapi.testclient import TestClient

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker, declarative_base
from sqlalchemy.pool import StaticPool

from app.db import get_session
from app.main import app
from app.models import Base, EmissionFactor

TEST_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
	poolclass=StaticPool,
	)

TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

@pytest.fixture()
def db_session() -> Iterator[Session]:
        
	Base.metadata.create_all(bind=engine)
	db = TestingSessionLocal()

	db.add_all(
		[
		EmissionFactor(category="travel", key="car", unit="km", co2e_per_unit=0.2, source="test",scope="direct"), #la till scope i lab2, uppgift3
		EmissionFactor(category="travel", key="train", unit="km", co2e_per_unit=0.02, source="test",scope="direct"), #la till scope i lab2, uppgift3
		EmissionFactor(category="food", key="beef", unit="portion", co2e_per_unit=5.0, source="test",scope="lifecycle"), #la till scope i lab2, uppgift3
		]
	)
	db.commit()

	try:
		yield db
	finally:
		db.close()

@pytest.fixture(scope="session", autouse=True)
def create_test_db():
	"""
	skapar alla tabeller i testdatabasen innan någon test körs
	körs en gång per test-session
	"""
	Base.metadata.create_all(bind=engine)
	yield
	Base.metadata.drop_all(bind=engine)

@pytest.fixture
def db_session():
	"""
	skapar en ny databas-session för varje test
	varje test får sin egen session (isolerar tester från varandra)
	"""
    
	Base.metadata.create_all(bind=engine)
	
	db = TestingSessionLocal()
	
	car_factor = EmissionFactor(
		category="travel",
		key="car",
		unit="km",
		co2e_per_unit=0.2,
		source="test",
        scope="direct",
	)
	db.add(car_factor)
	db.commit()
	
	try:
		yield db
	finally:
		db.close()
		Base.metadata.drop_all(bind=engine)
		
@pytest.fixture()
def client(db_session):
    """
    skapar en testclient mot fastAPI men med DB-dependency override.
    då använder API:T testdatabasen när tester körs.
    """
    def override_get_session():
        yield db_session
    app.dependency_overrides[get_session] = override_get_session
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()