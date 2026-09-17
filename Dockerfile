# ---- Stage 1: build the SvelteKit static frontend ----
FROM node:22-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci || npm install
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: Python backend that serves the built frontend ----
FROM python:3.12-slim AS app
WORKDIR /app

# Backend deps
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Backend source
COPY backend/app ./app

# Built frontend from stage 1 (served by FastAPI at /)
COPY --from=frontend /frontend/build ./frontend/build

# Spot seed data lives in /app/data (also the mounted volume target).
# spots.json is baked in; the SQLite cache is created at runtime in the volume.
COPY data/spots.json ./data/spots.json

ENV DATA_DIR=/app/data \
    SPOTS_FILE=/app/data/spots.json \
    DB_PATH=/app/data/waveometer.sqlite3 \
    FRONTEND_DIR=/app/frontend/build \
    FORECAST_DAYS=12 \
    CACHE_STALE_MIN=60 \
    REFRESH_INTERVAL_MIN=360

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
