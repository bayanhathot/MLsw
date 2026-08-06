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
- GET  /users/search
- GET  /users/{username}
- POST /friends/requests
- GET  /friends/requests/incoming
- GET  /friends/requests/outgoing
- POST /friends/requests/{id}/accept
- POST /friends/requests/{id}/decline
- DELETE /friends/requests/{id}
- GET  /friends
- DELETE /friends/{username}
- POST /posts
- GET  /posts/feed
- GET  /posts/{id}
- DELETE /posts/{id}
- POST /posts/{id}/like
- DELETE /posts/{id}/like
- GET  /posts/{id}/comments
- POST /posts/{id}/comments
- DELETE /posts/{id}/comments/{comment_id}
- POST /posts/{id}/share
- GET  /users/{username}/posts
- GET  /users/me/profile
- PATCH /users/me/profile
- GET  /users/{username}/stats
- POST /play-events
"""

import os

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.routers.auth import router as auth_router
from app.routers.sessions import router as sessions_router
from app.routers.mixes import router as mixes_router
from app.routers.posts import router as posts_router
from app.routers.users import router as users_router
from app.routers.friends import router as friends_router
from app.routers.profiles import router as profiles_router
from app.routers.play_events import router as play_events_router

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
    root_path=os.getenv("ROOT_PATH", ""),
)

app.mount(
    "/static",
    StaticFiles(directory="app/static"),
    name="static",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
app.include_router(sessions_router)

# Register mix generation endpoints.
# POST /mixes/start creates a new mix queue from Audius search results.
app.include_router(mixes_router)

# Register user lookup and friend request endpoints.
app.include_router(users_router)
app.include_router(friends_router)

# Register post (feed entry) endpoints.
app.include_router(posts_router)

# Register profile customization/stats and play-event tracking endpoints.
app.include_router(profiles_router)
app.include_router(play_events_router)


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
