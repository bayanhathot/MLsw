"""
base.py

Defines the shared SQLAlchemy Base class.

All database models inherit from Base.

Important:
Do not import models here.
If base.py imports User and user.py imports Base, that creates a circular import.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """
    Parent class for all SQLAlchemy models.
    """

    pass