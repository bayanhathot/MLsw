"""
models package

This package imports all SQLAlchemy models.

Alembic imports this package so all models are registered in Base.metadata.
"""

from app.database.models.user import User

__all__ = ["User"]