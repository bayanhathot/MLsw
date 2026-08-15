"""
database.py

This file is responsible for connecting the FastAPI backend to PostgreSQL.

Main responsibilities:
1. Read DATABASE_URL from the environment.
2. Create the SQLAlchemy engine.
3. Create a session factory.
4. Provide get_db(), which gives FastAPI endpoints a database session.
"""

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Load variables from .env when running locally.
# In Docker Compose, variables are also provided through env_file.
load_dotenv()

# Read the full database connection string.
# Example:
# postgresql+psycopg2://cuemix_user:cuemix_password@postgres:5432/cuemix_db
DATABASE_URL = os.getenv("DATABASE_URL")

# Fail early if DATABASE_URL is missing.
# This is better than getting a confusing database error later.
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set. Check your .env file.")

# The engine is SQLAlchemy's main database connection object.
#
# It does not mean "one open connection forever".
# Think of it as the connection manager that knows how to talk to PostgreSQL.
#
# pool_pre_ping=True checks connections before using them.
# This helps avoid errors from stale/broken connections.
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)

# SessionLocal is a factory for creating database sessions.
#
# autocommit=False:
#   We manually control when changes are committed.
#
# autoflush=False:
#   SQLAlchemy will not automatically push changes before every query.
#
# bind=engine:
#   This session factory uses the PostgreSQL engine above.
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def get_db():
    """
    FastAPI dependency that provides a database session.

    A database session is like a short conversation with the database:
    1. Open session.
    2. Use it inside an endpoint.
    3. Close session after the request finishes.

    The 'yield' keyword gives the session to the endpoint.
    The 'finally' block always closes the session, even if an error happens.
    """

    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()