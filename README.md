# Wave-o-meter

Personal surf forecast for 10 Irish west-coast spots. FastAPI backend +
SvelteKit frontend, single-container deploy. See `docs/SDD.md` for the design.

## Local testing (two terminals, hot-reload)

You need two processes in dev: the backend API and the Vite dev server
(which proxies `/api` to the backend).

### 1. Backend (terminal 1)
```bash
cd backend
python3 -m venv .venv          # first time only
. .venv/bin/activate
pip install -r requirements.txt   # first time only
uvicorn app.main:app --reload --host 127.0.0.1 --port 8080
```
The API is now at http://127.0.0.1:8080/api/health
(First start warms the cache in the background — the first `/api/overview`
may take a few seconds while it fetches all 10 spots.)

### 2. Frontend (terminal 2)
```bash
cd frontend
npm install                    # first time only
npm run dev
```
Open the URL Vite prints (usually http://localhost:5173).
`/api/*` calls are proxied to the backend on :8080 automatically.

## Test the production build locally (single process)

This mirrors how it runs in Docker — the backend serves the built SPA:
```bash
cd frontend && npm run build   # outputs frontend/build/
cd ../backend && . .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8080
# open http://127.0.0.1:8080  (whole app on one port)
```

## Docker (home server)
```bash
cp .env.example .env           # then edit: set a random GATE_SECRET
docker compose up -d --build   # http://<host-ip>:6767
```

### Access gate
Protected by a shared-answer gate (see `docs/SDD.md`). Config via `.env`:
- `GATE_ANSWER` — the answer (default: Dmitrius)
- `GATE_SECRET` — random string for signing session cookies (REQUIRED; generate
  with `python3 -c "import secrets;print(secrets.token_urlsafe(48))"`)
- `COOKIE_SECURE=1` — set when behind HTTPS (recommended for any public URL)

The gate is only meaningful over **HTTPS** — put it behind a TLS reverse proxy
for a public URL.

## Tests
```bash
cd backend && . .venv/bin/activate
python3 tests/run_all.py   # 39 offline tests (scoring, auth, engine)
```

## Notes
- **Fonts:** drop licensed Linear Sans woff2 files in `frontend/static/fonts/`
  (see the README there). Falls back to system sans otherwise.
- **Security:** LAN-only, no auth (SDD §3/§12). Do not expose to the internet
  without a reverse proxy + auth.
