# Zonix Backend README

Backend API for **Zonix — Smart AI DJ Mixer**.

The backend is responsible for the server-side logic of the project: authentication, database access, future music catalog metadata, segment metadata, saved mixes, liked segments, listening history, and social/profile features.

At the current stage, the backend includes:

- FastAPI application setup
- PostgreSQL database connection
- SQLAlchemy database session management
- Alembic migration infrastructure
- User authentication MVP
- Password hashing with bcrypt
- JWT access-token login
- Protected `/auth/me` endpoint
- Database health-check endpoint

---

## 1. Backend goal in the Zonix project

Zonix is a Smart AI DJ Mixer. The frontend is the user interface, but the backend is the part that owns the application logic and the database.

The backend should answer questions like:

- Who is the current user?
- Which songs and artists exist in the approved catalog?
- Which song segments are DJ-ready?
- Which segments did the user like?
- Which mixes did the user save?
- Which friends can view the user profile?
- What are the user’s top artists and songs?

The frontend should not connect directly to PostgreSQL. The correct flow is:

```text
Frontend
   |
   | HTTP request
   v
FastAPI Backend
   |
   | SQLAlchemy
   v
PostgreSQL Database
```

This keeps the data centralized, safer, and easier to control.

---

## 2. Current backend architecture

Current backend structure:

```text
backend/
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│
├── app/
│   ├── core/
│   │   ├── __init__.py
│   │   └── security.py
│   │
│   ├── database/
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   └── user.py
│   │   ├── base.py
│   │   └── database.py
│   │
│   ├── routers/
│   │   ├── __init__.py
│   │   └── auth.py
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── auth_service.py
│   │   └── session_manager.py
│   │
│   ├── main.py
│   └── schemas.py
│
├── alembic.ini
├── Dockerfile
└── requirements.txt
```

---

## 3. Main design decisions

### 3.1 Why FastAPI?

We use FastAPI because it is modern, fast, typed, and works naturally with Pydantic schemas.

For this project, FastAPI is useful because:

- It gives automatic API documentation at `/docs`.
- It supports dependency injection, which we use for database sessions.
- It works well with typed request and response models.
- It is suitable for APIs that may later serve frontend, mobile app, and desktop app clients.

---

### 3.2 Why PostgreSQL?

We use PostgreSQL because Zonix has relational data.

Examples:

```text
user likes segment
user saves mix
song belongs to artist
segment belongs to song
mix belongs to user
friendship connects two users
```

A relational database is good for this because it supports:

- tables
- relationships
- foreign keys
- indexes
- constraints
- transactions
- reliable persistence

PostgreSQL will eventually store:

- users
- artists
- songs
- song segments
- mixes
- liked segments
- listening history
- friend relationships
- public profile settings
- recent prompts

---

### 3.3 Why SQLAlchemy?

SQLAlchemy is the Python database layer.

Instead of writing raw SQL everywhere, we define Python classes that represent database tables.

Example:

```python
class User(Base):
    __tablename__ = "users"
```

This maps to a real PostgreSQL table called:

```text
users
```

SQLAlchemy gives us:

- models
- database sessions
- queries
- transactions
- a clean layer between FastAPI and PostgreSQL

---

### 3.4 Why Alembic?

SQLAlchemy defines the models in Python, but it does not automatically update the real PostgreSQL database in a controlled team-friendly way.

Alembic manages schema changes.

Example migration history:

```text
migration 1 -> create users table
migration 2 -> create artists table
migration 3 -> create songs table
migration 4 -> create song_segments table
```

This is important because every teammate needs the same database schema.

Do not manually create production tables in Adminer. Use Alembic migrations.

---

### 3.5 Why JWT authentication?

The backend currently uses JWT access tokens.

Flow:

```text
User registers
User logs in
Backend verifies password
Backend returns JWT token
Frontend sends token in future requests
Backend identifies current user from token
```

JWT is useful for the MVP because it is simple and works well for API-based applications.

Current protected endpoint:

```text
GET /auth/me
```

This endpoint proves that the backend can identify the current logged-in user.

---

### 3.6 Why hash passwords?

We never store real passwords.

Bad:

```text
password = "strongpassword"
```

Good:

```text
hashed_password = "$2b$..."
```

During registration:

```text
plain password -> bcrypt hash -> store hash
```

During login:

```text
typed password + stored hash -> verify match
```

The database stores only `hashed_password`.

The API response never returns `password` or `hashed_password`.

---

### 3.7 Why pin bcrypt version?

The backend uses:

```text
passlib==1.7.4
bcrypt==4.0.1
```

This is intentional.

Newer bcrypt versions can cause compatibility issues with Passlib 1.7.4, including errors related to bcrypt version metadata and the 72-byte password limit.

So we pin bcrypt to a version that works reliably with Passlib.

---

## 4. File-by-file explanation

### 4.1 `app/main.py`

Purpose:

- Creates the FastAPI app object.
- Registers routers.
- Defines basic health endpoints.

Important endpoints:

```text
GET /
GET /db-health
```

Important line:

```python
app.include_router(auth_router)
```

Without this line, the auth endpoints will not appear in `/docs`.

---

### 4.2 `app/database/database.py`

Purpose:

- Reads `DATABASE_URL`.
- Creates the SQLAlchemy engine.
- Creates the database session factory.
- Provides `get_db()`.

Main concepts:

```text
engine
    SQLAlchemy connection manager.

SessionLocal
    Factory that creates database sessions.

get_db()
    FastAPI dependency that gives each request a temporary database session.
```

Important idea:

```text
One request that needs the database
    -> gets one SQLAlchemy session
    -> uses it
    -> closes it after request finishes
```

A database session is not the same as a login session.

---

### 4.3 `app/database/base.py`

Purpose:

- Defines the shared SQLAlchemy `Base`.

All models inherit from it:

```python
class User(Base):
    ...
```

Important rule:

`base.py` should not import specific models like `User`.

Why?

Because this creates circular imports:

```text
user.py imports Base
base.py imports User
```

Correct direction:

```text
user.py imports Base
base.py imports nothing from models
```

---

### 4.4 `app/database/models/user.py`

Purpose:

Defines the `users` table.

Current fields:

```text
id
username
email
hashed_password
is_active
created_at
```

Important decisions:

- `id` is the primary key.
- `username` is unique.
- `email` is unique.
- `hashed_password` stores the password hash.
- `is_active` lets us disable accounts later.
- `created_at` stores account creation time.

---

### 4.5 `app/database/models/__init__.py`

Purpose:

Imports all database models in one package.

Example:

```python
from app.database.models.user import User
```

This helps Alembic discover models when generating migrations.

---

### 4.6 `app/core/security.py`

Purpose:

Contains security helper functions.

Main functions:

```text
hash_password()
verify_password()
create_access_token()
decode_access_token()
```

Responsibilities:

- Hash passwords during registration.
- Verify passwords during login.
- Create JWT tokens.
- Decode JWT tokens for protected endpoints.

This file should not contain HTTP route logic.

---

### 4.7 `app/services/auth_service.py`

Purpose:

Contains authentication business logic.

Main responsibilities:

- Find user by email.
- Find user by username.
- Register user.
- Login user.
- Create access token after successful login.

Why have a service layer?

Because routers should not contain all business logic.

Clean separation:

```text
router
    Handles HTTP.

service
    Handles business logic.

model
    Defines database table.

database.py
    Provides DB session.
```

---

### 4.8 `app/routers/auth.py`

Purpose:

Defines authentication HTTP endpoints.

Current endpoints:

```text
POST /auth/register
POST /auth/login
GET  /auth/me
```

`/auth/register`

- Validates request body.
- Calls `register_user`.
- Returns safe user data.

`/auth/login`

- Validates credentials.
- Returns JWT token.

`/auth/me`

- Requires `Authorization: Bearer <token>`.
- Decodes token.
- Loads the current user from PostgreSQL.
- Returns current user data.

---

### 4.9 `app/schemas.py`

Purpose:

Defines Pydantic schemas for API input and output.

Current schemas:

```text
UserCreate
UserLogin
UserRead
Token
```

Important difference:

```text
SQLAlchemy model
    Database shape.

Pydantic schema
    API request/response shape.
```

Example:

`User` model contains:

```text
hashed_password
```

But `UserRead` does not contain it.

This prevents password hashes from being returned to the frontend.

---

### 4.10 `alembic/env.py`

Purpose:

Connects Alembic to:

- the database URL
- SQLAlchemy `Base.metadata`
- imported models

Alembic uses this file when running:

```powershell
python -m alembic revision --autogenerate -m "message"
python -m alembic upgrade head
```

---

### 4.11 `requirements.txt`

Purpose:

Defines backend Python dependencies.

Important packages:

```text
fastapi
uvicorn
sqlalchemy
psycopg2-binary
python-dotenv
passlib
bcrypt
python-jose
email-validator
alembic
pytest
httpx
```

Whenever this file changes, rebuild Docker:

```powershell
docker compose build --no-cache backend
```

---

### 4.12 `Dockerfile`

Purpose:

Defines how to build the backend container.

Typical flow:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5000"]
```

Important decision:

```text
--host 0.0.0.0
```

This allows the FastAPI server to accept traffic from outside the container.

---

## 5. Environment variables

The project root `.env` should contain:

```env
POSTGRES_DB=zonix_db
POSTGRES_USER=zonix_user
POSTGRES_PASSWORD=zonix_password
POSTGRES_PORT=5432

DATABASE_URL=postgresql+psycopg2://zonix_user:zonix_password@postgres:5432/zonix_db
DATABASE_URL_LOCAL=postgresql+psycopg2://zonix_user:zonix_password@localhost:5432/zonix_db

SECRET_KEY=change_this_to_a_long_random_secret
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
```

Meaning:

```text
DATABASE_URL
    Used inside Docker containers.
    Host is postgres.

DATABASE_URL_LOCAL
    Used by local tools from PowerShell.
    Host is localhost.

SECRET_KEY
    Used to sign JWT tokens.

ALGORITHM
    JWT signing algorithm.

ACCESS_TOKEN_EXPIRE_MINUTES
    Access token lifetime.
```

Do not commit `.env`.

Commit `.env.example`.

---

## 6. How to run the backend with Docker

From the project root:

```powershell
docker compose down
docker compose up --build
```

Useful URLs:

```text
Frontend:
http://localhost:8080

Backend:
http://localhost:5000

Backend docs:
http://localhost:5000/docs

Adminer:
http://localhost:8081
```

---

## 7. How to check backend health

Open:

```text
http://localhost:5000/
```

Expected:

```json
{
  "service": "zonix-backend",
  "status": "running",
  "message": "Zonix backend is running"
}
```

Open:

```text
http://localhost:5000/db-health
```

Expected:

```json
{
  "database": "connected",
  "result": 1
}
```

Meaning:

```text
/ checks FastAPI itself.
/db-health checks FastAPI + PostgreSQL connection.
```

---

## 8. How to use Adminer

Open:

```text
http://localhost:8081
```

Login:

```text
System: PostgreSQL
Server: postgres
Username: zonix_user
Password: zonix_password
Database: zonix_db
```

Use Adminer to inspect:

- tables
- rows
- schema
- migration results

Current expected tables:

```text
users
alembic_version
```

---

## 9. How to run migrations

From the project root, start PostgreSQL:

```powershell
docker compose up -d postgres
```

Go to backend:

```powershell
cd backend
.\.venv\Scripts\activate
```

Generate a new migration:

```powershell
python -m alembic revision --autogenerate -m "describe change"
```

Apply migrations:

```powershell
python -m alembic upgrade head
```

Check current migration:

```powershell
python -m alembic current
```

Show migration history:

```powershell
python -m alembic history
```

Important:

After changing SQLAlchemy models, always create and apply a migration.

---

## 10. How to test authentication manually

### 10.1 Register

Go to:

```text
http://localhost:5000/docs
```

Call:

```text
POST /auth/register
```

Request body:

```json
{
  "username": "mrisatmo",
  "email": "mrisatmo@example.com",
  "password": "strongpassword"
}
```

Expected response:

```json
{
  "id": 1,
  "username": "mrisatmo",
  "email": "mrisatmo@example.com",
  "is_active": true
}
```

---

### 10.2 Duplicate register

Call the same register request again.

Expected:

```text
409 Conflict
```

This proves duplicate email/username checks work.

---

### 10.3 Login

Call:

```text
POST /auth/login
```

Request body:

```json
{
  "email": "mrisatmo@example.com",
  "password": "strongpassword"
}
```

Expected response:

```json
{
  "access_token": "long.jwt.token.here",
  "token_type": "bearer"
}
```

---

### 10.4 Wrong password

Call login with a wrong password:

```json
{
  "email": "mrisatmo@example.com",
  "password": "wrongpassword"
}
```

Expected:

```text
401 Unauthorized
```

---

### 10.5 Protected endpoint

Copy the token from login.

In Swagger UI, click:

```text
Authorize
```

Paste:

```text
Bearer YOUR_TOKEN_HERE
```

Call:

```text
GET /auth/me
```

Expected:

```json
{
  "id": 1,
  "username": "mrisatmo",
  "email": "mrisatmo@example.com",
  "is_active": true
}
```

This proves the complete backend auth flow works:

```text
register -> login -> token -> protected endpoint
```

---

## 11. How to test with PowerShell curl

Register:

```powershell
curl.exe -X POST "http://localhost:5000/auth/register" `
  -H "Content-Type: application/json" `
  -d "{\"username\":\"mrisatmo2\",\"email\":\"mrisatmo2@example.com\",\"password\":\"strongpassword\"}"
```

Login:

```powershell
curl.exe -X POST "http://localhost:5000/auth/login" `
  -H "Content-Type: application/json" `
  -d "{\"email\":\"mrisatmo2@example.com\",\"password\":\"strongpassword\"}"
```

Use `/auth/me`:

```powershell
curl.exe -X GET "http://localhost:5000/auth/me" `
  -H "Authorization: Bearer YOUR_TOKEN_HERE"
```

---

## 12. How to test password hashing directly

From project root:

```powershell
docker compose run --rm backend python -c "from app.core.security import hash_password; print(hash_password('strongpassword'))"
```

Expected output starts with:

```text
$2b$...
```

Check dependency versions:

```powershell
docker compose run --rm backend python -c "import bcrypt, passlib; print('bcrypt:', bcrypt.__version__); print('passlib:', passlib.__version__)"
```

Expected:

```text
bcrypt: 4.0.1
passlib: 1.7.4
```

---

## 13. Common problems and fixes

### Problem: `ModuleNotFoundError: No module named 'app.core.security'`

Cause:

- `security.py` missing
- file accidentally named `security,py`
- `core/__init__.py` missing
- Docker image not rebuilt

Fix:

```powershell
docker compose build --no-cache backend
```

Also verify:

```text
backend/app/core/security.py
backend/app/core/__init__.py
```

---

### Problem: circular import with `User`

Cause:

`base.py` imports `User`, while `user.py` imports `Base`.

Fix:

`base.py` should only define `Base`.

Do not import models inside `base.py`.

---

### Problem: bcrypt error about password length

Cause:

Incompatible bcrypt version with Passlib.

Fix requirements:

```text
passlib==1.7.4
bcrypt==4.0.1
```

Then rebuild:

```powershell
docker compose build --no-cache backend
```

---

### Problem: `relation "users" does not exist`

Cause:

The `User` model exists in Python, but the real PostgreSQL table was not created.

Fix:

```powershell
cd backend
python -m alembic revision --autogenerate -m "create users table"
python -m alembic upgrade head
```

---

### Problem: backend can connect in Docker, but Alembic cannot connect locally

Cause:

Docker uses:

```text
postgres
```

PowerShell uses:

```text
localhost
```

Fix:

Use both:

```env
DATABASE_URL=postgresql+psycopg2://zonix_user:zonix_password@postgres:5432/zonix_db
DATABASE_URL_LOCAL=postgresql+psycopg2://zonix_user:zonix_password@localhost:5432/zonix_db
```

---

## 14. Current auth readiness checklist

Backend Auth MVP is ready when all of this works:

```text
POST /auth/register works
POST /auth/login returns token
GET /auth/me works with token
GET /auth/me fails without token
Duplicate register returns 409
Wrong password returns 401
Password/hash is never returned in API response
```

Current status:

```text
Registration works.
Next checks:
- login
- /auth/me
- duplicate register
- wrong password
```

---

## 15. Git workflow

Before working:

```powershell
git checkout -b feature/backend-auth
```

Check changes:

```powershell
git status
```

Commit after auth works:

```powershell
git add backend/app
git add backend/requirements.txt
git add backend/alembic.ini
git add backend/alembic
git add .env.example
git commit -m "Add PostgreSQL-backed user authentication"
```

Do not commit:

```text
.env
backend/.venv
__pycache__
.pytest_cache
```

---

## 16. Next backend milestones

After backend auth MVP is confirmed, the next database modules are:

```text
artists
songs
song_segments
```

Recommended order:

```text
1. Create Artist model
2. Create Song model
3. Create SongSegment model
4. Generate Alembic migration
5. Apply migration
6. Add CRUD endpoints
7. Add tests
```

Why this order?

Because future features depend on them:

```text
liked_segments needs users + song_segments
listening_history needs users + songs/segments
mixes needs users + song_segments
top_artists needs users + artists + listening history
```

The foundation is:

```text
users
artists
songs
song_segments
```

Then we can add:

```text
liked_segments
saved_mixes
listening_history
friends
profile visibility
leaderboards
```

---

## 17. Developer rules for future backend work

1. Do not put everything in `main.py`.
2. Put HTTP endpoints in `routers/`.
3. Put business logic in `services/`.
4. Put database models in `database/models/`.
5. Put shared security/config logic in `core/`.
6. Put request/response schemas in `schemas.py` or later split into `schemas/`.
7. Every model change should get an Alembic migration.
8. Never commit `.env`.
9. Never return `hashed_password` from the API.
10. Test with `/docs`, curl, and database inspection before committing.
