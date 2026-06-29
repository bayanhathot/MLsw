# Zonix Frontend/Backend Connection Notes

## What was fixed

The frontend API file already contained real FastAPI calls:

- `startSession()` -> `POST http://localhost:5000/sessions/start`
- `sendFeedback()` -> `POST http://localhost:5000/sessions/{session_id}/feedback`
- `stopSession()` -> `POST http://localhost:5000/sessions/{session_id}/stop`

But `frontend/src/lib/stores/sessionStore.js` was still importing old mock function names:

- `startSessionMock`
- `sendFeedbackMock`
- `stopSessionMock`

That meant the UI was not truly connected to the backend and could fail during build/runtime.

The store now imports and uses the real API functions:

- `apiStartSession`
- `apiSendFeedback`
- `apiStopSession`

## How to run locally

Terminal 1:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 5000
```

Terminal 2:

```powershell
cd frontend
npm install
npm run dev
```

Open:

- Frontend: `http://localhost:5173`
- Backend health: `http://127.0.0.1:5000/health`
- Backend docs: `http://127.0.0.1:5000/docs`

## How to run with Docker Compose

From the project root:

```powershell
docker compose down
docker compose up --build
```

Open:

- Frontend: `http://localhost:8080`
- Backend: `http://127.0.0.1:5000/health`
