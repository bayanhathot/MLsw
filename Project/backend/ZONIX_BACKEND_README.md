# Zonix Backend README

This README explains the purpose, structure, and current behavior of the Zonix backend.

---

## 1. Backend purpose

The backend is the server-side brain of Zonix.

Its current purpose is to:

- Receive vibe prompts from the frontend.
- Validate requests.
- Create AI DJ sessions.
- Choose a mock song/moment based on the prompt.
- Store active sessions temporarily in memory.
- Accept user feedback.
- Stop active sessions.
- Return structured JSON responses to the frontend.

The backend does not display the UI. It provides the API and logic that the frontend uses.

---

## 2. Backend technology

The backend uses:

```text
Python
FastAPI
Pydantic
Uvicorn
Docker
```

Development server:

```text
http://127.0.0.1:5000
```

Interactive API documentation:

```text
http://127.0.0.1:5000/docs
```

---

## 3. Backend folder structure

```text
backend/
  app/
    __init__.py
    main.py
    schemas.py
    services/
      __init__.py
      session_manager.py
  Dockerfile
  .dockerignore
  requirements.txt
```

---

## 4. Important files

### `app/main.py`

Purpose:

This is the FastAPI entry point.

What it does:

- Creates the FastAPI app.
- Defines app title, description, and version.
- Adds CORS settings so the frontend can call the backend.
- Defines the health endpoint.
- Defines the session start endpoint.
- Defines the feedback endpoint.
- Defines the stop endpoint.

Current endpoints:

```text
GET  /health
POST /sessions/start
POST /sessions/{session_id}/feedback
POST /sessions/{session_id}/stop
```

---

### `app/schemas.py`

Purpose:

Defines request and response data shapes using Pydantic models.

Why this file exists:

FastAPI uses Pydantic schemas to validate request bodies and generate API documentation automatically.

Main schemas:

```text
StartSessionRequest
FeedbackRequest
NowPlaying
AIReasoning
SessionResponse
StopSessionResponse
```

Example start request:

```json
{
  "prompt": "emotional Arabic vocals with smooth transitions"
}
```

Example session response structure:

```json
{
  "id": "session_12345678",
  "prompt": "emotional Arabic vocals with smooth transitions",
  "status": "playing",
  "vibeLabel": "Emotional Arabic vocals",
  "nowPlaying": {
    "title": "Midnight Whispers",
    "artist": "Hassan Al-Shafei",
    "album": "Private Demo Catalog",
    "coverUrl": "/brand/zonix-logo.svg",
    "vibeLabel": "Emotional Arabic vocals"
  },
  "audioUrl": "",
  "reasoning": {
    "selectedMoment": "...",
    "transitionPlan": "...",
    "nextDirection": "..."
  },
  "selectedFeedback": null
}
```

---

### `app/services/session_manager.py`

Purpose:

Contains the current MVP session logic.

What it does now:

- Stores sessions in memory.
- Creates a new session ID.
- Chooses a mock track/moment using simple prompt keyword matching.
- Applies feedback by saving the selected feedback.
- Stops a session by changing its status.

Current session storage:

```python
SESSIONS = {}
```

Important:

This is temporary in-memory storage. All sessions disappear when the backend restarts.

---

## 5. Current API endpoints

### `GET /health`

Purpose:

Checks that the backend is running.

Example response:

```json
{
  "status": "ok",
  "service": "zonix-backend",
  "version": "0.1.0"
}
```

---

### `POST /sessions/start`

Purpose:

Starts a new AI DJ session from a user prompt.

Request body:

```json
{
  "prompt": "deep work focus with smooth transitions"
}
```

Backend behavior:

1. Strips whitespace from the prompt.
2. Rejects empty prompts with status 400.
3. Creates a session ID.
4. Chooses a mock session based on prompt keywords.
5. Stores the session in memory.
6. Returns the session to the frontend.

---

### `POST /sessions/{session_id}/feedback`

Purpose:

Receives coaching feedback from the frontend.

Request body:

```json
{
  "feedback": "More energy"
}
```

Backend behavior:

1. Checks that feedback is not empty.
2. Looks for the session ID.
3. Returns 404 if the session does not exist.
4. Stores the selected feedback.
5. Updates the reasoning `nextDirection` message.
6. Returns the updated session.

---

### `POST /sessions/{session_id}/stop`

Purpose:

Stops an active AI DJ session.

Backend behavior:

1. Looks for the session ID.
2. Returns 404 if the session does not exist.
3. Changes the session status to `stopped`.
4. Returns a stop confirmation response.

Example response:

```json
{
  "session_id": "session_12345678",
  "status": "stopped",
  "message": "AI DJ session stopped."
}
```

---

## 6. Current mock AI logic

The current backend does not yet contain a real ML model.

Instead, it uses simple keyword rules inside `choose_demo_track(prompt)`.

Current rules:

```text
If prompt contains "gym" or "energy"
→ return Gym energy session

If prompt contains "arabic" or "vocals"
→ return Emotional Arabic vocals session

If prompt contains "coding", "focus", or "work"
→ return Deep work focus session

Otherwise
→ return Smooth flow session
```

Purpose of this mock logic:

- Prove the backend decision pipeline.
- Let the frontend receive realistic session data.
- Prepare the project for real catalog/model logic later.

---

## 7. CORS configuration

The backend allows requests from these frontend origins:

```text
http://localhost:5173
http://127.0.0.1:5173
http://localhost:8080
http://127.0.0.1:8080
```

Why this is needed:

The frontend and backend run on different ports. Browsers block cross-origin requests unless the backend explicitly allows them.

---

## 8. Running the backend locally

From the backend folder:

```powershell
cd backend
```

Activate virtual environment on PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Run the server:

```powershell
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 5000
```

Open:

```text
http://127.0.0.1:5000/health
http://127.0.0.1:5000/docs
```

---

## 9. Running the backend in Docker

The backend Dockerfile:

```text
backend/Dockerfile
```

What it does:

1. Uses `python:3.11-slim`.
2. Copies `requirements.txt`.
3. Installs Python dependencies.
4. Copies the `app/` source folder.
5. Exposes port 5000.
6. Starts Uvicorn with host `0.0.0.0`.

Important:

Inside Docker, the backend must use:

```text
--host 0.0.0.0
```

not:

```text
--host 127.0.0.1
```

because `127.0.0.1` inside a container only points to the container itself.

---

## 10. Running backend with the whole project

From the project root:

```powershell
docker compose up --build
```

Backend URL:

```text
http://127.0.0.1:5000
```

Health check:

```text
http://127.0.0.1:5000/health
```

Docs:

```text
http://127.0.0.1:5000/docs
```

---

## 11. Manual API testing

### Health

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:5000/health
```

### Start session

```powershell
$body = @{
  prompt = "emotional Arabic vocals with smooth transitions"
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:5000/sessions/start `
  -ContentType "application/json" `
  -Body $body
```

### Send feedback

Replace `YOUR_SESSION_ID` with the returned session ID:

```powershell
$feedbackBody = @{
  feedback = "More energy"
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:5000/sessions/YOUR_SESSION_ID/feedback `
  -ContentType "application/json" `
  -Body $feedbackBody
```

### Stop session

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:5000/sessions/YOUR_SESSION_ID/stop
```

---

## 12. Current limitations

Current backend limitations:

- No real database yet.
- Sessions are stored only in memory.
- No real user authentication yet.
- No real song catalog yet.
- No real audio files yet.
- No real segment extraction yet.
- No real ML model yet.
- Feedback does not yet choose the next segment.
- No tests have been added yet.

---

## 13. Recommended next backend steps

Next backend milestone:

```text
Replace hardcoded prompt rules with catalog-based segment scoring.
```

Recommended tasks:

1. Create `backend/app/data/catalog.json`.
2. Add `catalog_loader.py`.
3. Add `segment_scorer.py`.
4. Make `/sessions/start` choose the best segment from the catalog.
5. Store session preferences such as target energy and target vocal level.
6. Make feedback update those preferences.
7. Add `POST /sessions/{session_id}/next`.
8. Add pytest tests.
9. Later add real audio processing.
10. Later add database persistence.

---

## 14. Backend summary

The backend currently works as a clean FastAPI MVP.

It provides:

```text
Health check
Session creation
Feedback handling
Session stopping
Mock AI DJ decision logic
Docker support
```

Its purpose is to act as the server/API brain of Zonix and prepare the project for real catalog, audio, and ML logic later.
