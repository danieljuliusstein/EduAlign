# EduAlign — AI Powered College Matcher

A full-stack web app that helps students find colleges based on the kind of experience they actually want, not just their stats.

## Background & Motivation

Most college search tools turn everything into a numbers game — GPA, SAT, acceptance rates. That stuff matters, but it’s not what your day-to-day life looks like once you’re there. You’re living on that campus for four years.

EduAlign focuses more on the experience side of things. Instead of only asking “where can I get in,” it tries to answer “where would I actually enjoy being.” The goal is simple: match students to colleges that fit how they want to live, not just what they score on paper.

## Approach & Methods

The matching system is built around a simple 3-step flow.

**Step 1 — Basics:** GPA, SAT, major, location, extracurriculars, school size, and tuition preferences.

**Step 2 — Experience:** Sliders for dimensions like academic intensity, social life, mental health culture, collaboration vs competition, and more. Sliders are pre-filled from the student’s profile, but you can tweak them however you want.

**Step 3 — Vibe:** Tags such as “entrepreneurial,” “creative,” or “study abroad,” plus free text for anything more specific.

From there, the system scores colleges across these dimensions and returns the top matches with a percentage score.

## Implementation

The frontend is React with a multi-step flow meant to feel smooth and not overwhelming. The results view uses radar charts to compare your preferences against each school, so you can see where things line up (and where they don’t).

The backend is Python (FastAPI): profile processing, auto-tuning for preferences, and the ranking / matching pipeline.

Additional tools around the core matcher:

- College reviews (pros / cons / advice)
- Financial planner
- Compare tool
- A dashboard to track and organize schools (dream, target, safety)

## Results

EduAlign returns a top set of matches with scores and visual breakdowns — not a black box.

Slider auto-fill makes it fast to get started, but you keep full control to adjust everything. The dashboard ties the workflow together so you can manage your list instead of losing it across tabs.

The app is live and fully deployed.

## Lessons Learned

Turning subjective ideas (“vibe,” “fit”) into something you can model and rank takes careful design.

The hardest part was feeling smart without feeling confusing. Slider auto-fill gives a strong starting point while making it clear you’re still in charge.

Multi-step UIs need discipline: if one step feels too heavy, people drop off, so ordering and copy matter.

## Future Work

- Expand the college dataset
- Improve the financial planning side
- Bring in more real student data for better accuracy
- Explore a chat-style interface instead of a long form
- Add practical touches like deadline alerts

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
