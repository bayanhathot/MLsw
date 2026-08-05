# Zonix — Smart AI DJ Mixer

Zonix is a full-stack AI DJ web app prototype. The goal of the project is to let a user describe a vibe, start an AI DJ session, and guide the session using feedback buttons such as **Good vibe**, **More energy**, **Less vocals**, and **Smoother**.

The important idea is that Zonix is not meant to be only a normal music player. The long-term goal is to select and mix the best **song moments/segments**, then transition between them like a DJ.

---

## 1. Project purpose

The purpose of this project is to build a working client/server MLOps-style application around an AI music mixing idea.

The current project proves these things:

- A frontend can collect a user music/vibe prompt.
- A backend can receive the prompt through an API.
- The backend can create an AI DJ session.
- The frontend can display the session result.
- The user can send feedback to the backend.
- The user can stop the session.
- The whole system can run with Docker Compose using separate frontend and backend containers.

Current MVP behavior:

```text
User writes prompt
→ Frontend sends prompt to backend
→ Backend creates mock AI DJ session
→ Frontend shows now-playing information
→ User sends feedback
→ Backend updates session state
→ User stops session
```

---

## 2. Current system architecture

```text
Project/
  frontend/             SvelteKit user interface
  backend/              FastAPI backend API
  docker-compose.yml    Runs frontend and backend together
```

High-level flow:

```text
User
↓
SvelteKit Frontend
↓ HTTP requests
FastAPI Backend
↓
Mock AI DJ session logic
↓
Session response
↓
Frontend player updates
```

---

## 3. Main modules

### Frontend module

Location:

```text
frontend/
```

Technology:

```text
SvelteKit
JavaScript with JSDoc
CSS
Nginx for Docker production serving
```

Purpose:

The frontend is the user-facing part of Zonix. It displays the landing page, prompt input, AI DJ player, feedback buttons, and login/register placeholder pages.

Main responsibilities:

- Show the Zonix UI.
- Let the user enter a vibe prompt.
- Send the prompt to the backend.
- Display the current AI DJ session.
- Let the user send coaching feedback.
- Let the user stop the AI DJ session.

Important frontend files:

```text
frontend/src/routes/+page.svelte
```

Main home page.

```text
frontend/src/lib/components/
```

Reusable UI components such as the navbar, prompt composer, hero section, feedback buttons, and AI DJ player card.

```text
frontend/src/lib/stores/sessionStore.js
```

Central frontend state manager. It stores the prompt, session status, current session, feedback, player state, and errors.

```text
frontend/src/lib/services/sessionApi.js
```

Frontend API layer. It sends HTTP requests to the FastAPI backend.

---

### Backend module

Location:

```text
backend/
```

Technology:

```text
FastAPI
Uvicorn
Pydantic
Python
```

Purpose:

The backend is the server-side logic of Zonix. It receives requests from the frontend, creates AI DJ sessions, stores temporary session state, accepts user feedback, and stops sessions.

Current backend endpoints:

```text
GET  /health
POST /sessions/start
POST /sessions/{session_id}/feedback
POST /sessions/{session_id}/stop
```

Important backend files:

```text
backend/app/main.py
```

FastAPI entry point. Defines the API app, CORS settings, and routes.

```text
backend/app/schemas.py
```

Defines request and response data shapes using Pydantic models.

```text
backend/app/services/session_manager.py
```

Contains the current MVP session logic. It creates sessions, chooses mock tracks based on prompt keywords, stores sessions in memory, applies feedback, and stops sessions.

---

### API connection module

The frontend and backend communicate using HTTP requests.

The frontend API file is:

```text
frontend/src/lib/services/sessionApi.js
```

It sends requests to:

```text
http://localhost:5000
```

Current API flow:

```text
Start AI DJ button
→ POST /sessions/start
→ backend returns session
→ frontend updates player
```

```text
Feedback button
→ POST /sessions/{session_id}/feedback
→ backend updates selected feedback
→ frontend updates session state
```

```text
Stop AI DJ button
→ POST /sessions/{session_id}/stop
→ backend marks session as stopped
→ frontend returns to stopped state
```

---

### Current AI/mock model module

The current backend does not contain the final machine learning model yet.

For the MVP, the backend uses simple keyword logic inside:

```text
backend/app/services/session_manager.py
```

Examples:

```text
Prompt contains "gym" or "energy"
→ choose Gym energy mock session

Prompt contains "arabic" or "vocals"
→ choose Emotional Arabic vocals mock session

Prompt contains "coding", "focus", or "work"
→ choose Deep work focus mock session
```

Purpose of this temporary logic:

- Prove that the frontend can send prompts to the backend.
- Prove that the backend can make a decision and return a session.
- Prepare the project for a real segment catalog and scoring model later.

Next AI step:

```text
Replace keyword rules with a segment catalog + scoring function.
```

### Temporary prompt-to-search fallback

The current Audius integration works best with short music keywords, while
users naturally write longer DJ instructions. For the current MVP, Zonix first
tries the original prompt and then uses a small keyword fallback when Audius
returns no results. Examples include:

```text
gym / workout / energy -> workout electronic
coding / focus / work  -> chill electronic
Arabic / vocals        -> Arabic
chill / relax          -> chill electronic
```

This is temporary rule-based behavior, not an LLM. A future version will
replace it with an LLM intent extractor that converts the prompt into validated
structured fields such as search queries, mood, energy, vocal preference, and
transition style. Audius will still provide real track candidates; the LLM
will interpret the request rather than invent songs or audio URLs.

---

### Database/catalog module

Current state:

There is no real database yet.

The backend currently stores sessions in memory:

```python
SESSIONS = {}
```

This means sessions disappear when the backend restarts. This is acceptable for the MVP.

Next planned step:

Create a catalog file:

```text
backend/app/data/catalog.json
```

The catalog will store song segments with fields such as:

```text
segment id
title
artist
mood tags
energy
vocal level
start second
end second
audio URL
cover URL
```

Later database options:

```text
SQLite       simple local database
PostgreSQL   production-ready relational database
Redis        temporary cache/session storage
```

Future database tables may include:

```text
users
songs
segments
sessions
feedback
saved_mixes
```

---

### Audio processing module

Current state:

The project does not yet perform real audio cutting, beat detection, or crossfading.

Future purpose:

The audio processing module will eventually:

- Load approved music files.
- Cut selected song segments.
- Normalize volume.
- Detect tempo/BPM.
- Crossfade between segments.
- Prepare playable audio for the frontend.

Possible future tools:

```text
ffmpeg
pydub
librosa
essentia
```

---

### Docker module

Docker is used to run frontend and backend as separate services.

Current containers:

```text
zonix-frontend   SvelteKit build served by Nginx on port 8080
zonix-backend    FastAPI served by Uvicorn on port 5000
```

Docker Compose file:

```text
docker-compose.yml
```

Purpose:

- Run frontend and backend together with one command.
- Keep each module isolated.
- Make the project easier to run on another computer.
- Prepare the project for a clean MLOps-style deployment structure.

Image vs container:

```text
Dockerfile = instructions/recipe
Image      = built package/template
Container  = running copy of the image
```

---

## 4. How to run the full project with Docker

From the project root:

```powershell
docker compose down
docker compose up --build
```

Open:

```text
Frontend: http://localhost:8080
Backend health: http://127.0.0.1:5000/health
Backend docs: http://127.0.0.1:5000/docs
```

Expected backend health response:

```json
{
  "status": "ok",
  "service": "zonix-backend",
  "version": "0.1.0"
}
```

---

## 5. How to test the full app manually

1. Run Docker Compose.
2. Open the frontend at `http://localhost:8080`.
3. Write a prompt such as:

```text
emotional Arabic vocals with smooth transitions
```

4. Click **Start AI DJ**.
5. Confirm the player changes to a playing session.
6. Click **More energy** or **Good vibe**.
7. Confirm the feedback is accepted.
8. Click **Stop AI DJ**.
9. Check backend logs for successful API requests.

Expected backend logs:

```text
POST /sessions/start 200 OK
POST /sessions/{session_id}/feedback 200 OK
POST /sessions/{session_id}/stop 200 OK
```

---

## 6. What has been completed so far

Completed:

- Created Zonix product direction.
- Built SvelteKit frontend UI.
- Added prompt composer.
- Added quick vibe presets.
- Added AI DJ player card.
- Added feedback/coach buttons.
- Added Stop AI DJ behavior.
- Added login/register placeholder pages.
- Added frontend state store.
- Added frontend API service layer.
- Built FastAPI backend.
- Added backend health endpoint.
- Added start session endpoint.
- Added feedback endpoint.
- Added stop session endpoint.
- Added request/response schemas.
- Added in-memory session storage.
- Connected frontend to backend.
- Added Dockerfile for frontend.
- Added Dockerfile for backend.
- Added Docker Compose to run both services together.
- Fixed SvelteKit template issue with `%sveltekit.head%` and `%sveltekit.body%`.

---

## 7. Current limitations

The current project is a working MVP, but it is not the final full AI DJ system yet.

Current limitations:

- No real user authentication yet.
- No real database yet.
- No real music catalog yet.
- No real audio playback or audio files yet.
- No real ML model yet.
- No real segment extraction yet.
- No real transition/crossfade engine yet.
- Feedback is stored but does not yet choose a next segment.

---

## 8. Next development steps

Recommended next steps:

1. Add `backend/app/data/catalog.json`.
2. Add a catalog loader service.
3. Add a segment scoring service.
4. Replace hardcoded keyword logic with catalog-based scoring.
5. Make feedback affect the next selected segment.
6. Add `POST /sessions/{session_id}/next` endpoint.
7. Add backend tests with pytest.
8. Add real audio files or demo audio URLs.
9. Add basic audio playback in the frontend.
10. Later, add real ML/audio processing.

The next important milestone is:

```text
Backend chooses from a real segment catalog using a scoring function.
```

---

## 9. Project summary

Zonix currently works as a full-stack MVP:

```text
Frontend UI
+ FastAPI backend
+ API connection
+ Docker Compose
+ mock AI DJ session logic
```

The purpose of the current version is to prove the product pipeline before adding real music processing and machine learning.
