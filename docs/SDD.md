# Wave-o-meter — Software Design Document (lean)

Status: FINAL (v1) · Owner: (you) · Last updated: 2026-09-17

A personal surf-forecast web app ("Wave-o-meter") for Irish west-coast spots.

---

## 1. Overview & goals

A personal surf-forecast web app for a fixed set of Irish west-coast spots,
deployed on a home server for single-user access. It shows an interactive,
hour-by-hour view of surf conditions on a 0–5 scale, backed by the wave model
that the feasibility spike proved most accurate for Irish waters (ECMWF), with a
confidence indicator derived from multi-model agreement.

**Primary goals**
- Accurate, trustworthy *open-ocean conditions* forecast (swell, wind, tide) for
  10 preloaded spots.
- A modern, semi-interactive hourly UI: scrub through the day, see a 0–5 rating
  per hour (Surfline-style feel).
- Hand-authored local knowledge per spot (skill level, best swell/wind, tide
  behaviour, hazards).
- Runs unattended in Docker on a home server.

**What makes this better than commercial apps (for me specifically):** the local
spot metadata is tuned to my breaks, the rating logic is transparent (not a black
box), and it honestly shows when the forecast is uncertain.

## 2. Scope

**In scope (v1)**
- 10 fixed spots (see §7), metadata preloaded.
- Fetch + cache forecast data on a schedule.
- 0–5 rating per spot per hour, rules-based.
- Confidence indicator from model spread.
- Interactive hourly timeline UI, **12-day outlook** (days 1–7 full-confidence,
  days 8–12 shown as a dimmed long-range outlook — see §8).

**Non-goals (v1)** — explicitly deferred:
- Beating Surfline on *breaking-wave quality* at the sand/reef. Not feasible from
  public data (see §14). We forecast conditions, not the exact wave.
- Arbitrary spot lookup / search. Fixed list only for now.
- Multi-user, accounts, auth. Single user on a trusted LAN.
- Session logging / ML calibration. Designed for (see §13) but not built in v1.

## 3. Constraints & assumptions

- **Data must be free and legal.** No scraping Surfline/surf-forecast. Confirmed
  sources: Open-Meteo (marine incl. tide, + wind), Marine Institute ERDDAP
  (buoys, for the accuracy scorecard). All resolved in §4.
- Single user, home server, Docker. Low traffic.
- **Security:** v1 assumes a trusted LAN with no auth. If ever exposed beyond the
  LAN, it MUST go behind a reverse proxy with auth — flagged as a hard gate, not
  an afterthought.
- Must tolerate a data-source outage gracefully (serve last-good cache, show
  staleness).

## 4. Data sources (validated in spike)

| Purpose | Source | Notes |
|---|---|---|
| Wave models | Open-Meteo Marine API | ECMWF WAM = primary (spike: MAE ~0.2 m, corr ~0.97). meteofrance_wave + EWAM for spread. |
| Wind | Open-Meteo Forecast API | Speed + direction; critical for rating. |
| Tides | Open-Meteo Marine API (`sea_level_height_msl`) | RESOLVED: same API, no key. Continuous tidal height, classified to low/mid/high per hour (see §6). |
| Model accuracy | Marine Institute ERDDAP buoys (M4, M6) | Offshore buoys for the historical model-accuracy scorecard. |

No API keys required for Open-Meteo or ERDDAP. Frontend is SvelteKit (chosen for
a modern interactive UI that is lighter to build and self-host solo than React).

## 5. Architecture

```
                +-------------------+
                |  SvelteKit UI     |   hourly timeline, spot view
                +---------+---------+
                          | HTTP (JSON)
                +---------v---------+
                |  FastAPI backend  |   scoring, caching, endpoints
                +----+---------+----+
                     |         |
       +-------------v+       +v--------------+
       | Scheduled     |      | SQLite         |
       | fetcher       |      | beaches,       |
       | (Open-Meteo)  |      | forecast cache,|
       +-------+-------+      | model-accuracy |
               |             +----------------+
   Open-Meteo / ERDDAP (external)
```

- **Backend:** Python + FastAPI. Owns data fetching, the 0–5 scoring function,
  caching, and the JSON API.
- **Refresh strategy (two layers):**
  1. **On app open / login** — when the UI loads, it calls the API, which checks
     cache freshness. If the cached forecast is older than a staleness threshold
     (default 60 min), it triggers a refresh so the user always sees current
     conditions + the next 12 days on open. If cache is fresh, it serves
     immediately (no wait). A stale-while-revalidate option can serve cache
     instantly and refresh in the background.
  2. **Background scheduler** — a periodic job (APScheduler in-process) refreshes
     all spots every 6 h regardless of visits, so the cache is usually warm and
     the on-open path rarely blocks. Open-Meteo updates only a few times daily,
     so 6 h is ample.
  - The UI never calls Open-Meteo directly — only the FastAPI API. A per-source
    rate-guard prevents redundant upstream calls if multiple loads coincide.
- **Storage:** SQLite — spot metadata, cached forecasts, model-accuracy history.
- **Frontend:** SvelteKit. Talks only to the FastAPI JSON API.
- **Deploy:** Docker Compose (backend + static frontend). One box, home server.

## 6. The 0–5 scoring model (core)

The heart of the app. A transparent, rules-based function per spot per hour.

**Inputs (per hour):** swell height, swell period, swell direction, wind speed,
wind direction, tide state (derived — see below).

**Per-spot config drives it** (see §7 schema): each spot declares its optimal
swell direction window, optimal wind (offshore bearing), workable swell-height
range, and tide preference. Reefs (Easkey L/R) use tighter direction/tide
weighting than beaches.

**Tide derivation:** Open-Meteo gives `sea_level_height_msl` as a continuous
curve. Per spot per hour we classify it into low / mid / high by position within
that day's local min–max range (e.g. bottom third = low). The spot's `tide`
preference (`low`, `mid`, `high`, `any`, or a range like `low-mid`) is then
matched against it.

**Sketch of the logic:**
```
base     = f(swell_height, swell_period)     # size & power, clamped to spot range
swellDir = penalty as swell bearing falls outside optimal_swell_dir window
wind     = bonus near offshore (optimal_wind_dir), penalty toward onshore,
           scaled by wind speed (light wind matters less)
tide     = penalty if classified tide state is wrong for the spot
rating   = clamp(base * swellDir * wind * tide, 0, 5)
```
Direction matching uses angular distance (handles the 0/360 wrap). Reefs get a
steeper direction/tide penalty curve than beaches. Exact curves and weights are
left to implementation and will be tuned against observation over time.

**Output:** a 0–5 float (shown rounded/graded) + the component breakdown, so the
UI can explain *why* a rating is what it is.

**The 0–5 scale (Surfline-style labels):**

| Rating | Label | Meaning |
|---|---|---|
| 0 | No surf | Flat or unsurfable — no rideable waves. |
| 1 | Very poor | Barely rideable; wrong size, blown out, or badly off. |
| 2 | Poor | Surfable but compromised — small, weak, or messy. |
| 3 | Fair | Worth a surf; decent but not dialled in. |
| 4 | Good | Clean, well-suited conditions; a good session. |
| 5 | Very good | Everything lines up — size, period, offshore wind, right tide. |

Mapping rules:
- The engine produces a continuous 0–5 score; the **label** comes from the
  rounded/banded value (e.g. 3.5–4.49 → "Good").
- **0 ("No surf") is a hard floor**, not just a low score: forced when swell
  height is below the spot's workable minimum (`swell_height_m[0]`) regardless of
  other factors — no swell means no surf, even in perfect wind.
- A **5 ("Very good")** requires all components strong at once: swell in the
  optimal direction window, adequate size *and* period, near-offshore wind, and a
  favourable tide. Any single bad factor caps the ceiling.
- The API returns both the numeric score and the label so the UI can colour-band
  the timeline (e.g. grey→red→orange→yellow→green→blue) like Surfline.

## 7. Spot metadata schema

Ten spots, confirmed and seeded in `data/spots.json`. Reef vs beach matters —
reefs care far more about swell direction and tide, beaches are more forgiving.

```jsonc
{
  "id": "lahinch",
  "name": "Lahinch",
  "aka": "Killard",                    // optional alternate name
  "county": "Clare",
  "lat": 52.9321, "lon": -9.3459,      // confirmed
  "break_type": "beach",               // beach | reef | point
  "skill": "beginner",                 // beginner | intermediate | advanced
  "optimal_swell_dir": [225, 315],     // degrees window (where swell comes FROM)
  "optimal_wind_dir": [45, 100],       // offshore bearing window (wind FROM)
  "swell_height_m": [0.8, 3.0],        // workable range
  "tide": "low-mid",                   // low | mid | high | any | range
  "hazards": "Rocks and rips near the pier at higher tides.",
  "notes": "...",
  "orientation_verified": true         // false = placeholder to confirm later
}
```

**The 10 spots (all coordinates + orientation confirmed):**
- Clare: Doughmore, Lahinch, Fanore, White Strand (aka Killard)
- Sligo: Easkey Left (reef), Easkey Right (reef), Strandhill
- Mayo: Bertra, Keel
- Kerry: The Magharees (aka Mossies)

All orientation data is verified from surf-forecast descriptions + owner's local
knowledge, **except Bertra** (`orientation_verified: false`) — inferred from The
Magharees (similar exposed sand beach) and to be confirmed after surfing it.

## 8. Confidence indicator & forecast horizon

The app shows a **12-day** outlook. Confidence is derived from **model spread**
(ECMWF vs meteofrance_wave vs EWAM) at each hour, but the number of available
models — and
thus the confidence signal — shrinks with the horizon (verified against
Open-Meteo):

| Horizon | Models available | Confidence quality |
|---|---|---|
| Days 1–3 | ECMWF + meteofrance_wave + EWAM | Full three-model spread |
| Days 4–10 | ECMWF + meteofrance_wave | Two-model spread |
| Days 11–12 | ECMWF only | No spread — long-range outlook only |

> **Model choice note:** GWAM (global WAM) was dropped during implementation — its
> coarse grid resolves nearshore Irish points partly onto land (~0.5 m at Lahinch
> while ECMWF/EWAM read ~2.3 m), which poisoned the spread and forced permanent
> "low confidence". meteofrance_wave resolves the coast well and reaches ~day 10.
> Spread thresholds: high ≤0.30 m, medium ≤0.60 m, else low (verified live).

Rules:
- **Days 1–7:** small spread (models agree) → high confidence; large spread →
  low confidence ("forecast uncertain"). Thresholds from spike data (mean spread
  ~0.2 m, occasional ~0.8 m).
- **Days 8–12:** ECMWF still produces a rating, but with no second model there is
  no spread to measure. These days are shown **dimmed and labelled "long-range,
  low confidence."** This also respects the physical reality that wave-forecast
  skill drops sharply after ~7 days — the spike's ~7% accuracy is a near-term
  figure, not a 12-day one. The UI must not present day 11 with the same
  authority as day 1.

## 9. Data model (SQLite)

- `spots` — the metadata from §7 (seeded from `data/spots.json`).
- `forecast_cache` — (spot_id, valid_time, model, wave_height, wave_period,
  wave_direction, wind_speed, wind_dir, sea_level_height, fetched_at). Feeds
  scoring and the model spread.
- `model_accuracy` — (buoy, model, window, MAE, RMSE, corr) from the spike-style
  buoy validation; lets the app say "ECMWF is most reliable here" and could later
  weight the rating.

## 10. API design (as built)

- `GET /api/spots` → spot metadata, county-ordered (Clare → Sligo → Mayo → Kerry).
- `GET /api/overview` → **home-page payload**: every spot with its current rating
  and **7 days of daypart summaries** (morning/midday/evening: score, height,
  wind, confidence). One call powers the whole home page. Resilient: a spot that
  fails to fetch is returned with `pending: true` (or `stale: true` if served
  from old cache) rather than 500-ing the page.
- `GET /api/spots/{id}/forecast?days=12` → **detail-page payload**: hourly
  ratings + conditions (swell/wind/tide) + confidence + breakdown, PLUS a `days`
  array of daypart summaries for the scrubber.
- `GET /api/summary` → **surf-weather-news digest**: a verdict headline, current
  best spots, best windows this week, and a day-by-day narrative of swell
  evolution + weather impact (uses one regional weather fetch).
- `GET /api/accuracy` → model-accuracy scorecard (placeholder).

JSON only; the UI is a pure client of this.

## 11. UI / UX (lean)

**Mobile-first** — the app is designed for a phone first, then scaled up to
desktop. The primary use case is checking conditions on your phone before driving
to a beach, so phone layout is the default target, not an afterthought.

Mobile-first principles applied throughout:
- Design and build the phone layout first; use `min-width` media queries to
  progressively enhance for tablet/desktop (never desktop-down).
- Single-column, vertically-scrolling layouts by default; multi-column only as an
  enhancement on wider viewports.
- Touch-first: large tap targets (spot cards, the hourly scrubber), no
  hover-only interactions — the "why this rating" breakdown opens on tap, not
  hover. Swipe/drag to scrub the timeline.
- Readable outdoors on a small screen: large rating numerals, high contrast,
  generous spacing.
- Performance-conscious: the one-call `/api/overview` keeps the home page light
  on mobile data; assets (incl. the self-hosted font) kept lean.

Two screens: a **home page** listing all spots grouped by county, and a **detail
page** per spot with rich swell/wind/tide breakdown.

### Home page — overview of all 10 spots
- Spots **grouped by county, in this order: Clare, Sligo, Mayo, Kerry** (Clare
  first). Each county is a labelled section.
- Within a county, one **card per spot** showing at a glance:
  - Spot name (and `aka` if present, e.g. "White Strand / Killard").
  - **Current 0–5 rating with its label** (No surf … Very good), colour-banded.
  - A compact next-few-hours strip (mini sparkline of the rating today).
  - Key facts: current wave height, wind (speed + on/offshore arrow), tide state.
  - `break_type` + `skill` tags (beach/reef, beginner/advanced).
- Clicking a card opens that spot's detail page.
- Clare order and county grouping come from the API (spots carry `county`; the UI
  orders counties Clare → Sligo → Mayo → Kerry).

### Detail page — rich per-spot view
The interactive piece. For the selected spot:
- **12-day hourly timeline** you can scrub across, showing the 0–5 rating per
  hour, colour-banded. Days 8–12 dimmed + labelled "long-range outlook" (§8).
- **Three clean, separated breakdown panels** for the selected hour:
  - **Swell** — height (m), period (s), direction (compass + arrow), and how well
    it matches the spot's optimal swell window.
  - **Wind** — speed, direction (compass + arrow), and on/cross/offshore state
    relative to the spot (offshore = good, shown clearly).
  - **Tide** — current height on the day's tidal curve, classified low/mid/high,
    with the spot's tide preference indicated.
- **Confidence badge** on the selected hour (§8).
- **"Why this rating" breakdown** — the component contributions (swell/wind/tide)
  so a 3 vs a 5 is explained, not just asserted.
- **Local knowledge panel** — hand-authored notes (skill, hazards, tide
  behaviour, best conditions) always visible.
- An **honesty note** — a short line that this forecasts offshore conditions, not
  the exact breaking wave (§14 risk).

Modern, clean, responsive. Surfline's hourly scrubber + condition cards are the
reference feel. Phone is the primary target (checking before a drive); desktop is
the enhanced layout.

### Visual design & typography
- **Primary font family: "Linear Sans"**, applied app-wide as the base font.
  - Load it via `@font-face` (self-hosted woff2 in the frontend assets) so the
    home server has no external font dependency and it works offline on the LAN.
    Bundle the licensed font files under the web assets; do not hotlink.
  - CSS stack with graceful fallback:
    `font-family: "Linear Sans", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;`
  - A monospace face is used only for dense numeric tables if needed; everything
    else (headings, body, labels, ratings) is Linear Sans.
- **Aesthetic:** clean, modern, lots of whitespace, minimal chrome. The content
  (rating + conditions) is the focus, not decoration.
- **Rating colour bands** carry meaning (grey→red→orange→yellow→green→blue for
  0→5); never rely on colour alone — always pair with the text label for
  accessibility (colour-blind safe).
- **Responsive** and touch-friendly; readable outdoors (good contrast, large
  rating numerals). Dark mode is a nice-to-have, not required for v1.
- Design tokens (colours, spacing, type scale) defined once in CSS variables so
  the look stays consistent across the home and detail pages.

## 12. Deployment

Runs on the home server via **Docker Compose**, accessible from any device on the
LAN whenever you want.

**Services:**
- `backend` — FastAPI + in-process APScheduler + the scoring engine. Exposes the
  JSON API. Owns all upstream calls to Open-Meteo/ERDDAP.
- `web` — built SvelteKit app. Either served as static files by the backend
  DECIDED: served by the FastAPI backend as a static SPA build (adapter-static),
  so the whole app is a single container. FastAPI mounts /_app assets and falls
  back to index.html for client routes (e.g. /spot/lahinch) on deep-link/refresh.

**Compose sketch:**
```yaml
services:
  surf:
    build: .
    ports:
      - "6767:8080"            # access at http://<home-server-ip>:6767
    volumes:
      - ./data:/app/data       # spots.json + SQLite persist across restarts
    environment:
      - REFRESH_INTERVAL_MIN=360   # background refresh (6 h)
      - CACHE_STALE_MIN=60         # on-open refresh threshold
      - FORECAST_DAYS=12
    restart: unless-stopped        # comes back after a reboot
```

- **Persistence:** SQLite + `spots.json` on a mounted `./data` volume so cache,
  spot data and accuracy history survive restarts and image rebuilds.
- **Always-on:** `restart: unless-stopped` means the app is up whenever the home
  server is, so opening the URL just works.
- **On-open refresh:** loading the page triggers the freshness check in §5, so
  you always land on current conditions + the next 12 days without manual action.
- **Access:** `http://<home-server-ip>:6767` on the LAN. Optionally a hostname
  via local DNS / hosts entry.
- **Security gate (unchanged):** LAN-only in v1, no auth. Exposing beyond the LAN
  (e.g. port-forward or public DNS) MUST first go behind a reverse proxy
  (Caddy/Traefik/nginx) with auth + TLS. This is a hard prerequisite, not
  optional — an unauthenticated internet-exposed service is out of scope for v1.

## 13. Future work

- **Session logging + calibration** — the real long-term edge. Log observed
  conditions over time and learn local corrections. Schema is designed to allow
  adding an `observations` table without rework.
- **Arbitrary spot lookup** — generalise beyond the fixed 10.
- **Weight rating by model accuracy** — use `model_accuracy` to lean on the
  historically-best model automatically.

## 14. Decisions made & remaining open questions

**Resolved during design:**
- **Frontend:** SvelteKit (lighter to build/self-host solo than React).
- **Tide source:** Open-Meteo `sea_level_height_msl` — same API, no extra source.
- **Spots:** all 10 coordinates + orientation confirmed and seeded (bar Bertra,
  inferred and flagged).
- **Preferred names:** Killard → White Strand; Mossies → The Magharees (both keep
  an `aka`). The Magharees is a beach break (sand); Doughmore is a beach break.

**Remaining open questions (non-blocking):**
- **Q:** Scheduler refresh cadence — every 3 h or 6 h? (Open-Meteo updates a few
  times daily; 6 h is likely plenty.)
- ~~SvelteKit served by FastAPI vs a separate static container.~~ RESOLVED:
  single container — FastAPI serves the static SvelteKit build.
- **Q:** Bertra orientation — confirm after first surf; currently inferred.

**RISK (headline, unchanged):** the last mile — open-ocean swell → how it
actually breaks on a specific sand/reef — is unmeasurable from public data. The
spike proved ~7% accuracy on *offshore swell*, not on the breaking wave. The app
must set this expectation honestly in the UI (a short "conditions, not a
guarantee" note on the spot view).

---

## 15. Implementation notes (as built)

This section records decisions and fixes made during implementation that refine
or correct the design above.

### Project layout
```
surf-app/
  backend/   FastAPI app (app/) + tests + .venv + requirements.txt
  frontend/  SvelteKit SPA (adapter-static)
  data/      spots.json (seed) + waveometer.sqlite3 (runtime cache)
  docs/SDD.md
  Dockerfile, docker-compose.yml, README.md
```

Backend modules: `config`, `spots`, `scoring`, `tide`, `confidence`,
`dayparts`, `openmeteo`, `forecast`, `cache`, `summary`, `main`.

### Data / model fixes
- **GWAM dropped → meteofrance_wave** for the confidence spread: GWAM's coarse
  grid resolves nearshore Irish points onto land (~0.5 m at Lahinch vs ~2.3 m),
  poisoning the spread. (See §8 note.)
- **Confidence uses RELATIVE spread** (spread ÷ mean), not absolute: nearshore
  models genuinely disagree ~1.6 m on average, so absolute thresholds flagged
  everything "low". Thresholds: high ≤0.48, medium ≤0.79, else low.
- **Tide fetched separately**: `sea_level_height_msl` must be requested WITHOUT
  the `models` param (it's a base marine var; requesting it with wave models
  returns all-null). This was a real bug — tide had been stuck at "mid".

### Networking / reliability
- **httpx instead of urllib**, with **IPv4 forced** (`local_address` /
  `FORCE_IPV4` env, default on): WSL/home-server networks often resolve
  Open-Meteo to IPv6 with no IPv6 route → "Network is unreachable"; urllib also
  stalled intermittently. httpx + IPv4 + retries cut a full refresh from ~317s
  to ~32s.
- **Parallel fetching**: the 3 calls per spot run concurrently, and spots
  refresh in parallel (`REFRESH_CONCURRENCY`, default 5).
- **Non-blocking startup + resilient overview**: cache warms in the scheduler
  thread so the app is ready immediately; `/api/overview` never 500s on a single
  spot failure (returns `pending`/`stale`).

### UI (as built)
- **Home**: mobile-first. Each spot card is a **horizontally scrollable** row of
  days (weekday + surf-height + 3 daypart bars + confidence symbol). Quality and
  confidence shown as coloured symbols, minimal text. A collapsible legend
  explains the bars/colours/symbols. A **Summary** button opens the surf-weather
  digest (§10 `/api/summary`).
- **Detail**: Surfline-style horizontal **day scrubber**; selecting a day shows
  an hourly table (Time · Surf · Swell · Wind · Tide) for **6am–11pm only**.
  Recommended hours (Fair+ and near the day's best) are outlined.
- **Surf-face height**: displayed heights are ~0.6× significant wave height
  (surfers quote the breaking face, not open-ocean Hs). Display only — scoring
  uses raw Hs. Applied consistently in frontend and the summary.
- **Fonts**: Linear Sans via self-hosted `@font-face`; files not bundled
  (licensed) — falls back to system sans until added to `frontend/static/fonts/`.

### Deployment
- Single container: multi-stage Dockerfile builds the SvelteKit static site, the
  Python image serves it via FastAPI (mounts `/_app`, SPA fallback to
  index.html). `docker-compose.yml`: host port 6767, `./data` volume, env config,
  `restart: unless-stopped`. LAN-only, no auth (see §3/§12 security gate).

### Post-review hardening (4-pass code review)
- `summary.build_summary` split into focused section builders; magic thresholds
  named as constants; "good day" count is now data-driven (was substring-matching
  its own generated prose).
- Swapped `print()` diagnostics for the `logging` module (configurable LOG_LEVEL).
- Removed dead code (`_today_strip`, unused `math` import).
- httpx client singleton now lock-guarded (double-checked) for thread safety.
- Promoted `scoring.window_center_and_half` to public (was a cross-module private
  helper access from forecast.py).
- CORS tightened from `*` to a configurable dev allowlist (`CORS_ORIGINS`); prod
  serves the SPA same-origin so none is needed.
- Startup confirmed non-blocking (warm-up runs in the scheduler thread).
- Noted but deferred (personal project, owner opted out): unit tests for
  `confidence`, `tide`, `dayparts`, `summary`.

### Access gate (public URL protection)
Since the app is exposed on a public home-server URL, a lightweight shared-answer
gate was added (`auth.py` + `/api/gate/*` + a `Gate.svelte` screen):
- Question: "What is the name of my surfboard?" (answer checked SERVER-SIDE only;
  never sent to the browser). Case/whitespace-insensitive, constant-time compare.
- Success sets an HMAC-signed, expiring cookie (`GATE_SECRET`). Guesses are
  limited to 3 per IP (`GATE_MAX_TRIES`) then a 15-min lockout; a correct answer
  during lockout is still refused.
- Middleware protects the data API and app routes; gate API, health and static
  assets stay open so the gate page can render. API calls without a valid cookie
  get 401; page loads render the gate client-side.
- Config: GATE_ENABLED, GATE_QUESTION, GATE_ANSWER, GATE_SECRET, GATE_MAX_TRIES,
  GATE_LOCKOUT_S, GATE_SESSION_S, COOKIE_SECURE.
- **HONEST LIMITATION:** this is a deterrent, not strong security (one shared
  secret, no accounts). It is only meaningful over HTTPS — for a public URL, put
  it behind a TLS reverse proxy (e.g. Caddy) and set COOKIE_SECURE=1. Without
  TLS the answer and cookie travel in plaintext.

### Richer data (v1.1)
- **Swell / wind-wave separation** (`swell_wave_*`, `wind_wave_height` from
  Open-Meteo marine base vars): the detail table's "Sea" column shows whether the
  hour is clean groundswell or messy windsea — the key surf-quality distinction
  that total wave height hides.
- **Sea surface temperature** per spot (wetsuit call), shown in the day header.
- **Marine Institute live buoys** (`buoys.py` + `/api/buoys`): a "Measured
  offshore now" panel on the home page with real Hs/period/SST from the M6/M3/M2
  buoys (data.marine.ie ERDDAP) — legitimate open ground-truth beside the
  forecast. 30-min cache; degrades gracefully if unreachable.
- **Daily weather extras** (weather_code, sunrise/sunset, UV) added to the
  weather fetch for the narrative.
- **Ensemble note:** attempted to widen the model ensemble, but re-confirmed GFS/
  ICON aren't on Open-Meteo's marine endpoint and GWAM still resolves nearshore
  Irish spots onto land — so the trustworthy spread stays ECMWF + meteofrance_wave
  (+ ewam near-term). Richness came from extra *variables*, not more models.
- **NOTE on scraping:** owner asked about scraping Surfline/surf-forecast for a
  local deploy; declined — ToS violation + Surfline bot-protection. Added the
  legitimate buoy + variable data instead.

### Known follow-ups
- Dayparts bucket by UTC hour (~1h off Irish summer local); could localise.
- `model_accuracy` scorecard endpoint is a placeholder (buoy-validation job from
  the spike not yet ported).
- Session logging / calibration (§13) still future work.
