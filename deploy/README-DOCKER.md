# Campus Copilot — Docker (local)

This stack runs:

- **frontend** — Nginx Alpine on host port **8080** (static UI + reverse proxy)
- **backend** — FastAPI / Uvicorn on the Docker network (`backend:8000`)

Persistent data lives on the **host** under `deploy/data/`, not inside image layers.

## Prerequisites

- Docker Desktop (or Docker Engine + Compose v2)
- Project-root `.env` (copy from `.env.example` and set real secrets)
- Existing SQLite DB + uploads copied into `deploy/data/` (see below)

## First-time data setup (preserve existing corpus)

1. Stop any local uvicorn writing to `backend/campus_copilot.db`.
2. Take a verified backup (see **Backup and restore**).
3. Copy into persistent data (do **not** overwrite originals):

```powershell
# From repo root (example)
Copy-Item backend\campus_copilot.db deploy\data\campus_copilot.db
New-Item -ItemType Directory -Force -Path deploy\data\uploaded_documents
Copy-Item backend\uploaded_documents\* deploy\data\uploaded_documents\
```

4. Confirm inventory with SQLite before `compose up` (expect the counts from your latest known-good backup).

Never run seed/ingest scripts as container startup.

## Configure secrets

```powershell
Copy-Item .env.example .env
# Edit .env: GEMINI_API_KEY, JWT_SECRET, USE_MOCK_LLM=false, CONFIDENCE_THRESHOLD=0.72
```

`JWT_SECRET` must not remain the example placeholder on any shared host.

## Start

```powershell
docker compose up -d --build
```

Open **http://localhost:8080/**

Health (via Nginx proxy): **http://localhost:8080/health**

## Stop / recreate (keep data)

```powershell
docker compose down
docker compose up -d --build
```

**Do not** use `docker compose down -v` for normal work. Persistent SQLite and uploads live in `deploy/data/` bind mounts; `-v` is reserved for destroying named volumes and is unsafe if volumes are added later.

## Backup and restore

Docker volumes/bind mounts are **not** backups. Always copy data out before upgrades.

### Backup (consistent SQLite + uploads)

1. Prefer stopping the stack so nothing is writing:

```powershell
docker compose stop backend
```

2. Use SQLite’s online backup API (safe even if the file is present):

```powershell
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$dest = "deploy\backups\backup_$ts"
New-Item -ItemType Directory -Force -Path "$dest\uploaded_documents" | Out-Null

python -c "import sqlite3; s=sqlite3.connect('deploy/data/campus_copilot.db'); d=sqlite3.connect('$dest/campus_copilot.db'.replace('\\','/')); s.backup(d); s.close(); d.close()"

Copy-Item deploy\data\uploaded_documents\* $dest\uploaded_documents\
```

3. Verify row counts and file counts in the backup folder before continuing.
4. Do **not** auto-delete older backups.

Take a backup before:

- Updating application images
- Changing Compose/volume layout
- Deploying a new version
- Any future schema migration

### Restore

1. `docker compose down`
2. Replace `deploy/data/campus_copilot.db` and `deploy/data/uploaded_documents/` from a verified backup
3. `docker compose up -d`
4. Re-check `/health` and inventory counts

## Persistent storage map

| Host path | Container path | Purpose |
|-----------|----------------|---------|
| `./deploy/data/campus_copilot.db` | `/data/campus_copilot.db` | SQLite (users, docs, chunks/embeddings, calendar, evals, chats) |
| `./deploy/data/uploaded_documents` | `/data/uploaded_documents` | Original uploaded files |

New uploads, ingestions, deletions, supersession, calendar edits, feedback, and evaluation runs all write here and survive container recreation.

## Git safety

Do not commit:

- `.env`
- `*.db`
- `backend/uploaded_documents/`
- `deploy/data/`
- `deploy/backups/`

## Deployment note

This Dockerization is for **local container verification**. Public hosting still needs HTTPS, a strong `JWT_SECRET`, Gemini outbound network access, and durable disk for `deploy/data/` (or equivalent mounts).
