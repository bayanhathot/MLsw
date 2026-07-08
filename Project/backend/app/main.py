"""
main.py

Entry point of the FastAPI backend.

This file is responsible for:
1. Creating the FastAPI app object.
2. Registering routers, such as the auth router.
3. Defining basic health-check endpoints.
4. Defining the database health-check endpoint.

Current backend routes:
- GET  /
- GET  /db-health
- POST /auth/register
- POST /auth/login
- GET  /auth/me
"""

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.routers.auth import router as auth_router


# ---------------------------------------------------------
# Create FastAPI app
# ---------------------------------------------------------
# This object is what Uvicorn runs from the Dockerfile.
#
# In the Dockerfile, we run:
# uvicorn app.main:app --host 0.0.0.0 --port 5000
#
# Meaning:
# app.main -> this file: backend/app/main.py
# app      -> this FastAPI object below
app = FastAPI(
    title="Zonix Backend",
    description="Backend API for the Zonix Smart AI DJ Mixer project.",
    version="0.1.0",
)


# ---------------------------------------------------------
# Register routers
# ---------------------------------------------------------
# Routers let us split endpoints into separate files.
#
# Instead of putting register/login/me directly inside main.py,
# we keep them in:
# backend/app/routers/auth.py
#
# This keeps main.py clean and makes the project easier to grow.
app.include_router(auth_router)


# ---------------------------------------------------------
# Basic backend health endpoint
# ---------------------------------------------------------
@app.get("/")
def root():
    """
    Simple backend health endpoint.

    Purpose:
    Check that the FastAPI server itself is running.

    Important:
    This endpoint does NOT test PostgreSQL.
    It only proves that the backend container/app is alive.
    """

    return {
        "service": "zonix-backend",
        "status": "running",
        "message": "Zonix backend is running",
    }


# ---------------------------------------------------------
# Database health endpoint
# ---------------------------------------------------------
@app.get("/db-health")
def db_health(db: Session = Depends(get_db)):
    """
    Database health-check endpoint.

    Purpose:
    Check that FastAPI can connect to PostgreSQL.

    How it works:
    1. A client sends GET /db-health.
    2. FastAPI sees db: Session = Depends(get_db).
    3. FastAPI calls get_db().
    4. get_db() opens a SQLAlchemy database session.
    5. This endpoint sends SELECT 1 to PostgreSQL.
    6. PostgreSQL returns 1.
    7. FastAPI returns a JSON response.
    8. get_db() closes the database session.

    Why SELECT 1?
    SELECT 1 is a tiny SQL query.
    It does not require any tables.
    This lets us test the database connection before creating real tables
    like users, artists, songs, and song_segments.
    """

    result = db.execute(text("SELECT 1")).scalar()

    return {
        "database": "connected",
        "result": result,
    }