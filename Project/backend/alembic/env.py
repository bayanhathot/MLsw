"""
alembic/env.py

Alembic environment file.

This file connects Alembic to:
1. Our PostgreSQL database.
2. Our SQLAlchemy models.
3. Our Base.metadata object.

Alembic uses this file when we run commands like:

    python -m alembic revision --autogenerate -m "create users table"
    python -m alembic upgrade head
"""

import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

# Import Base so Alembic can read the metadata of all SQLAlchemy models.
from app.database.base import Base

# Import all models so they are registered inside Base.metadata.
# If we do not import the models, Alembic may not detect the tables.
from app.database import models  # noqa: F401


# Alembic Config object.
# This gives access to values inside alembic.ini.
config = context.config


# Configure Python logging using alembic.ini.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


# Load the root .env file.
#
# env.py is located in:
#   backend/alembic/env.py
#
# Project root is two levels above:
#   backend/alembic -> backend -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


# Alembic needs a database URL.
#
# Prefer DATABASE_URL_LOCAL because we usually run Alembic from PowerShell.
# DATABASE_URL_LOCAL uses localhost.
#
# If DATABASE_URL_LOCAL does not exist, fall back to DATABASE_URL.
database_url = os.getenv("DATABASE_URL_LOCAL") or os.getenv("DATABASE_URL")

if not database_url:
    raise RuntimeError(
        "No database URL found. Set DATABASE_URL_LOCAL or DATABASE_URL in .env."
    )


# Override sqlalchemy.url from alembic.ini using our .env value.
config.set_main_option("sqlalchemy.url", database_url)


# This is the metadata Alembic compares against the real database.
#
# Example:
# If Base.metadata contains User table but PostgreSQL does not,
# Alembic autogenerate will create a migration for users.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Run migrations without creating a live database connection.

    This mode generates SQL scripts.
    We usually do not use this during normal local development.
    """

    url = config.get_main_option("sqlalchemy.url")

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={
            "paramstyle": "named",
        },
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations with a live database connection.

    This is the normal mode when we run:
        python -m alembic upgrade head
    """

    configuration = config.get_section(config.config_ini_section)

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


# Alembic decides whether it is running offline or online.
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
