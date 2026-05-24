# The Irons Backend

A FastAPI backend service.

## Requirements

- Python 3.12+
- A virtual environment (`.venv` already present in this repo)

## Setup

```bash
source .venv/bin/activate

pip install -r requirements-dev.txt

cp .env.example .env
```

## Run

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Then open:

- API root: http://localhost:8000/
- Swagger UI: http://localhost:8000/api/v1/docs
- ReDoc: http://localhost:8000/api/v1/redoc
- Health: http://localhost:8000/api/v1/health

## Project layout

```
app/
  main.py              # FastAPI app factory + lifespan
  config.py            # Settings (pydantic-settings)
  api/
    router.py          # Aggregates all route modules
    routes/
      health.py        # /health endpoint
      runeprofile.py   # /runeprofile/* proxy to api.runeprofile.com
  services/
    runeprofile.py     # Async client for the RuneProfile public API
  schemas/             # Pydantic response/request models
tests/                 # Pytest suite
```

## RuneProfile integration

The `/api/v1/runeprofile/*` routes proxy [RuneProfile](https://github.com/ReinhardtR/runeprofile)'s
public API. Configure these in `.env`:

- `RUNEPROFILE_USERNAME` — your in-game display name; used by `/runeprofile/me`.
- `RUNEPROFILE_API_KEY` — optional, raises the upstream rate limit from
  30 to 120 requests/min (request one in their Discord).
- `RUNEPROFILE_USER_AGENT` — set to something identifiable so the upstream
  maintainers can reach you (a Discord handle works well).

Endpoints (all under `/api/v1/runeprofile`):

| Method | Path | What it returns |
|---|---|---|
| `GET` | `/me` | Full profile for `RUNEPROFILE_USERNAME`. |
| `GET` | `/{username}` | High-level summary. |
| `GET` | `/{username}/full` | Skills, quests, collection log, diaries, and combat achievements in one payload. |
| `GET` | `/{username}/skills` | Skill levels and experience. |
| `GET` | `/{username}/quests` | Quest completion status. |
| `GET` | `/{username}/achievement-diaries` | Diary completion per area and tier. |
| `GET` | `/{username}/combat-achievements` | Combat achievement completion per tier. |
| `GET` | `/{username}/collection-log` | Full collection log. |
| `GET` | `/{username}/collection-log/{tab}` | A single tab (e.g. `Bosses`). |
| `GET` | `/{username}/collection-log/{tab}/{page}` | A single page (e.g. `Bosses/Abyssal Sire`). |
| `GET` | `/{username}/activities` | Paginated activity feed. |

Activity feed query params:

- `cursor` — opaque cursor returned by a previous response.
- `direction` — `next` (default) or `prev`.
- `limit` — items per page, 1–50 (default 20).
- `activityTypes` — comma-separated filter, e.g. `xp_milestone,quest_completed`.

Responses are passed through verbatim from the upstream API. The upstream
caches for ~1 minute, so polling more often is wasted work. Tab and page
names are case-insensitive and may contain spaces (URL-encode them as
`%20`, e.g. `/collection-log/Bosses/Abyssal%20Sire`).

## Adding a new endpoint

1. Create `app/api/routes/<feature>.py` with an `APIRouter`.
2. Define request/response models in `app/schemas/<feature>.py`.
3. Register the router in `app/api/router.py`.

## Testing

```bash
pytest
```

## Linting

```bash
ruff check .
ruff format .
```
