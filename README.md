# EduAlign

Find colleges that match your experience, not just your stats.

## Stack

- **Backend:** FastAPI (Python) — auth, college matching, financial plans, compare.
- **Frontend:** React (Vite + TypeScript) + Plotly.js — Find Your Match, Financial Planner, Compare Colleges.

## Run locally

1. **Backend** (from project root):
   ```bash
   pip install -r requirements.txt
   uvicorn main:app --reload
   ```
   API: http://localhost:8000

2. **Frontend:**
   ```bash
   cd frontend && npm install && npm run dev
   ```
   App: http://localhost:5173 (proxies `/api` to the backend).

## Deploy

**Frontend (e.g. Cloudflare Pages):** `cd frontend && npm run build` → deploy `frontend/dist/`. In Pages, set **`VITE_API_BASE_URL`** to your public API origin (no trailing slash), e.g. `https://edualign-api.fly.dev`. The built app calls that host for `/api/...`. Leave unset only if the UI and API share the same origin (or you use a reverse proxy). `public/_redirects` enables SPA routing on Pages.

**Backend:** run `uvicorn main:app --host 0.0.0.0`. Set **`CORS_ORIGINS`** to your frontend URL(s), comma-separated (e.g. `https://your-app.pages.dev,https://yourdomain.com`). Set **`DATABASE_URL`** to Postgres in production (see `.env.example`); keep using SQLite only for single-machine dev if you prefer.

**Local dev:** do not set `VITE_API_BASE_URL`; Vite proxies `/api` to `http://localhost:8000` (`vite.config.ts`).
