# Zonix — Smart AI DJ Mixer

Zonix is a full-stack AI DJ web app prototype. The goal of the project is to let a user describe a vibe, start an AI DJ session, and guide the session using feedback buttons such as **Good vibe**, **More energy**, **Less vocals**, and **Smoother**.

The important idea is that Zonix is not meant to be only a normal music player. The long-term goal is to select and mix the best **song moments/segments**, then transition between them like a DJ.

---

## 1. Project purpose

The purpose of this project is to build a working client/server MLOps-style application around an AI music mixing idea.

### Current social product flow

The current application also supports persistent and social mixes:

```text
User starts a mix from the homepage
-> POST /mixes/start creates a private draft in PostgreSQL
-> the first stored segment starts playing
-> the draft appears in Library
-> the owner publishes it
-> other users discover, play, like, and save it
-> two users who follow each other become friends
-> friends' published mixes appear in the Friends feed
```

The Community interface intentionally has only two views:

- **Friends**: published mixes from mutual friends.
- **Discover**: all published community mixes.

Following is still the action used to form a friendship, but there is no separate Following feed tab.

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

The frontend is the user-facing part of Zonix. It displays the landing page, prompt input, AI DJ player, authentication pages, Community feed, personal Library, and social mix controls.

Main responsibilities:

- Show the Zonix UI.
- Let the user enter a vibe prompt.
- Send the prompt to the backend.
- Display the current AI DJ session.
- Let the user send coaching feedback.
- Let the user stop the AI DJ session.
- Let authenticated users publish, like, save, and play mixes.
- Let users follow each other and browse Friends or Discover.

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

The backend is the server-side logic of Zonix. It authenticates users, creates persistent mix drafts, stores segments and social relationships in PostgreSQL, and serves the Community and Library APIs.

Current backend endpoints:

```text
POST   /auth/register
POST   /auth/login
GET    /auth/me
POST   /mixes/start
GET    /mixes/mine
GET    /mixes/saved
GET    /mixes/feed?scope=friends|discover
POST   /mixes/{mix_id}/publish
PUT    /mixes/{mix_id}/like
PUT    /mixes/{mix_id}/save
PUT    /users/{user_id}/follow
DELETE /users/{user_id}/follow
GET    /users/me/friends
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

The older session manager remains for the original session endpoints. The active homepage flow uses `backend/app/routers/mixes.py`, Audius search, and persistent database models.

---

### API connection module

The frontend and backend communicate using HTTP requests.

The main frontend API files are:

```text
frontend/src/lib/services/sessionApi.js
frontend/src/lib/services/mixApi.js
```

It sends requests to:

```text
http://localhost:5000
```

Current API flow:

```text
Start AI DJ button
→ POST /mixes/start
→ backend stores a draft and its segments
→ frontend starts the first segment
→ draft appears in Library
```

```text
Post mix
→ POST /mixes/{mix_id}/publish
→ mix appears in Discover
→ friends can also see it in Friends
```

```text
Follow another creator
→ PUT /users/{user_id}/follow
→ reciprocal follows become a friendship
→ friends' mixes appear in the Friends feed
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

Zonix uses PostgreSQL with SQLAlchemy models and Alembic migrations. Current persistent tables include:

```text
users
mixes
mix_segments
mix_likes
saved_mixes
user_follows
alembic_version
```

Persistent data includes user accounts, generated draft/published mixes, ordered segment plans, likes, saves, and directional follows. Friendship is derived from two reciprocal follow rows rather than stored in a separate table.

The remaining catalog work is to enrich tracks and segments with machine-learning features such as:

```text
mood
energy
BPM
musical key
vocal level
embedding/vector features
transition compatibility
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
3. Register or log in.
4. Enter a prompt such as `emotional Arabic vocals with smooth transitions`.
5. Click **Start AI DJ** and confirm the first returned segment plays.
6. Open Library and confirm the generated mix appears as a draft.
7. Publish the draft and confirm it appears under Community → Discover.
8. Log in with a second account in another browser profile.
9. Like and save the first account's mix.
10. Follow the first account.
11. From the first account, follow the second account back.
12. Confirm both accounts now show **Friends** and published mixes appear in the Friends view.

Expected backend logs:

```text
POST /mixes/start 200 OK
POST /mixes/{mix_id}/publish 200 OK
GET  /mixes/feed?scope=discover 200 OK
PUT  /users/{user_id}/follow 200 OK
GET  /mixes/feed?scope=friends 200 OK
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
- Added PostgreSQL-backed registration, login, logout, and authenticated user state.
- Added frontend state store.
- Added frontend API service layer.
- Built FastAPI backend.
- Added backend health endpoint.
- Added persistent mix generation through `/mixes/start`.
- Added feedback endpoint.
- Added stop session endpoint.
- Added request/response schemas.
- Added PostgreSQL models and Alembic migrations.
- Added draft editing and publishing.
- Added Community and Library pages.
- Added likes and private saved-mix bookmarks.
- Added directional follows and mutual friendship detection.
- Added Friends and Discover feed views.
- Connected the homepage player to the first generated mix segment.
- Connected frontend to backend.
- Added Dockerfile for frontend.
- Added Dockerfile for backend.
- Added Docker Compose to run both services together.
- Fixed SvelteKit template issue with `%sveltekit.head%` and `%sveltekit.body%`.

---

## 7. Current limitations

The current project is a working MVP, but it is not the final full AI DJ system yet.

Current limitations:

- Track selection is still Audius search plus rule-based prompt fallback, not the planned LLM/ML ranking system.
- The player currently plays only the first stored segment.
- No real ML model yet.
- No real segment extraction yet.
- No real transition/crossfade engine yet.
- Feedback is stored but does not yet choose a next segment.

---

## 8. Next development steps

Recommended next steps:

1. Add an LLM intent extractor that returns validated mood, energy, vocal, genre, and transition preferences.
2. Add audio/metadata features such as BPM, key, energy, and embeddings.
3. Rank real track and segment candidates against the structured prompt.
4. Score adjacent segment compatibility and choose a coherent sequence.
5. Make the player advance through every segment with correct boundaries.
6. Add beat-aware crossfades and transition rendering.
7. Make coaching feedback affect later selections.
8. Add backend and frontend automated tests.

The next important milestone is:

```text
LLM intent extraction + ML segment ranking + continuous matched playback.
```

---

## 9. Project summary

Zonix currently works as a full-stack MVP:

```text
Frontend UI
+ FastAPI backend
+ API connection
+ PostgreSQL persistence and Alembic migrations
+ authenticated accounts
+ persistent drafts and publishing
+ Community Friends/Discover feed
+ likes, saves, follows, and mutual friendships
+ Docker Compose
+ Audius-backed track candidates
```

The current version proves the full product and social pipeline. The next phase is improving music intelligence and multi-segment audio transitions.
