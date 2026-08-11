"""
user.py

This file defines the users table.

The User model represents one registered user in Zonix.

Important:
We never store the real password.
We only store hashed_password.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.core.time import utc_now


class User(Base):
    """
    SQLAlchemy model for the users table.

    Each object of this class represents one row in the users table.
    """

    # Name of the table inside PostgreSQL.
    __tablename__ = "users"

    # Primary key.
    # autoincrement=True means PostgreSQL generates the next id automatically.
    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
        autoincrement=True,
    )

    # Public username shown in the app.
    # unique=True prevents two users from having the same username.
    username: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        index=True,
        nullable=False,
    )

    # Email used for login.
    # unique=True prevents two accounts with the same email.
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )

    # Hashed password, not the real password.
    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    # Allows us to disable accounts later without deleting them.
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    # Account creation time.
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
        nullable=False,
    )

    mixes = relationship("Mix", back_populates="owner", cascade="all, delete-orphan")
