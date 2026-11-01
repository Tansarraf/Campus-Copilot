# Campus Copilot

Campus Copilot is a retrieval-augmented campus assistant. Students and administrators ask questions about circulars, fees, hostel rules, scholarships, placements, exams and other indexed university documents. Answers are grounded in retrieved passages, cited to source files, and withheld when the corpus is not confident.

The supported deployment for this release is **Docker Compose**: Nginx serves the static UI and reverse-proxies the FastAPI API at [http://localhost:8080/](http://localhost:8080/).

## Problem statement

Campus information is scattered across PDFs, Word files and notices. Students need answers that are accurate, attributable and honest about gaps. Campus Copilot indexes uploaded documents, retrieves the most similar chunks with cosine similarity, and generates a Gemini answer only from that evidence. If similarity stays below a threshold, the assistant abstains instead of guessing.

## Key features

- Student chat with citations and conversation history
- Admin document ingest, catalogue, supersession and deletion
- JWT authentication with separate admin and student login paths
- Shared academic calendar (admin publish, student view)
- Evaluation dashboard over persistent Evaluation Framework v2 runs
- Change-password for authenticated admin and student accounts
- Dockerized local stack with bind-mounted SQLite and uploads

## Architecture

```
Browser (http://localhost:8080)
        │
        ▼
Nginx (frontend container)
  - static HTML/CSS/JS
  - reverse proxy: /auth, /query, /documents, /admin, …
        │
        ▼
FastAPI / Uvicorn (backend container)
  - JWT auth, RAG query, ingest, calendar, evaluation
        │
        ├── SQLite  /data/campus_copilot.db
        └── files   /data/uploaded_documents
              ▲
              │ bind mounts
        host: deploy/data/
```

The frontend is same-origin. `frontend/app.js` uses an empty `API_BASE` so the browser calls `/auth/...` on port 8080; Nginx forwards those paths to `backend:8000`.

## Technology stack

| Layer | Choice |
|-------|--------|
| Frontend | HTML, CSS, vanilla JavaScript |
| Gateway | Nginx Alpine |
| API | Python 3.12, FastAPI, Uvicorn |
| Auth | JWT (PyJWT), bcrypt via passlib |
| Database | SQLite |
| Embeddings / generation | Google Gemini (`langchain-google-genai`) |
| Retrieval | NumPy / scikit-learn cosine similarity over stored vectors |
| Packaging | Docker Compose |

This release does **not** use React, PostgreSQL, Redis, FAISS, or a separate vector database.

## RAG pipeline

1. **Ingest.** An administrator uploads PDF, DOCX, Markdown or TXT. Text is extracted, chunked (`CHUNK_SIZE` / `CHUNK_OVERLAP`), embedded with Gemini, and stored as BLOBs in `chunks` together with document metadata.
2. **Query.** The student question is embedded with the same model. The retriever ranks chunks by cosine similarity and keeps the top `TOP_K`.
3. **Abstention.** If the best score is below `CONFIDENCE_THRESHOLD`, the API returns a grounded “not covered” style answer instead of a speculative completion.
4. **Generation.** Otherwise Gemini is asked to answer using only the retrieved passages. The UI shows cited sources.
5. **Logging.** Queries, feedback and evaluation runs are written to SQLite for the admin dashboard.

Embeddings and generation share one API key. Startup checks that the query embedder matches the index metadata so a mock index cannot be queried with live Gemini vectors (and vice versa).

## Document ingestion workflow

1. Sign in as an administrator.
2. Open **Documents** and upload a file with title/category metadata.
3. The backend stores the original under `DOCUMENTS_DIR`, extracts text, chunks, embeds and indexes immediately.
4. Students see the catalogue and can retrieve from the new chunks without a restart.
5. Admins can supersede or permanently delete a document (file, extracted text and index rows).

Docker does **not** auto-run seed or ingest scripts on startup. The persistent database and upload directory are the source of truth.

## Gemini integration

| Setting | Role |
|---------|------|
| `GEMINI_API_KEY` | Live embeddings and generation |
| `GEMINI_EMBEDDING_MODEL` | Default `models/gemini-embedding-001` |
| `GEMINI_GENERATION_MODEL` | Default `gemini-3.8-flash` |
| `USE_MOCK_LLM=true` | Deterministic fake embeddings and templated extractive answers (offline tests) |

If the key is missing or left as a placeholder, the backend falls back to mock mode. Retrieval quality and evaluation numbers are only meaningful with a real key and a matching Gemini index.

## Authentication and roles

- **Admin login:** `POST /auth/admin/login` with username and password. Non-admin accounts are rejected even with a valid password.
- **Student login:** `POST /auth/student/login` with an 11-digit enrollment number and password.
- Passwords are hashed with **bcrypt** (`app.auth.hash_password` / `verify_password`).
- Identity for authorization is the JWT `sub` (user id), reloaded from SQLite. Clients cannot set their own role.
- Public self-registration is disabled. Students are provisioned by an administrator (`backend/scripts/provision_students_TEMPLATE.py`).
- **Change password:** `POST /auth/change-password` requires the current password. The JWT selects the account; the body must not include a user id.

Local `scripts/seed_users.py` can create a bootstrap admin only when `INITIAL_ADMIN_PASSWORD` is set in the environment. The script does not run at API or Docker startup and never overwrites existing users.

## Student functionality

- Chat with citations and saved conversations
- Document catalogue (read)
- Shared academic calendar
- Profile onboarding for fields the administrator left blank
- Change password

## Admin functionality

- All student-facing chat/documents/calendar views
- Document upload, ingest, supersession and deletion
- Calendar event create/update/publish
- Insights, query logs and feedback
- Evaluation overview, retrieval analysis, run history

Admin-only HTTP routes return **403** for student tokens.

## Calendar

Administrators maintain a single published calendar. Students see the same events. There is no per-student private calendar in this version.

## Evaluation framework

Evaluation Framework v2 lives under `backend/app/evaluation/` and `backend/evaluation/`.

- Pack **`synthetic_v1`**: fictional campus seed documents and a labeled `benchmark.json`. Safe to publish; it is not a real university corpus.
- Pack **`university_v1`**: reserved and empty until a genuine annotated corpus exists.
- `python scripts/evaluate.py --benchmark synthetic_v1` appends a new SQLite run (never overwrites history) and can write JSON under `evaluation/results/` (that folder is gitignored).
- The admin UI reads persistent runs from SQLite. Do not commit live evaluation history or the production database.

## Docker architecture

| Service | Image | Host |
|---------|--------|------|
| `frontend` | Nginx 1.27 Alpine | `8080:80` |
| `backend` | Python 3.12, Uvicorn | internal `8000` |

Bind mounts:

| Host | Container |
|------|-----------|
| `./deploy/data/campus_copilot.db` | `/data/campus_copilot.db` |
| `./deploy/data/uploaded_documents` | `/data/uploaded_documents` |

Compose reads secrets from project-root `.env` (`env_file: .env`).

## Local installation (without Docker)

Requires **Python 3.12**.

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp ../.env.example .env            # or copy backend/.env.example
# Set GEMINI_API_KEY and JWT_SECRET. For local SQLite use:
# DATABASE_PATH=./campus_copilot.db
# DOCUMENTS_DIR=./uploaded_documents
# Windows PowerShell: $env:INITIAL_ADMIN_PASSWORD = "..."
export INITIAL_ADMIN_PASSWORD=...
python scripts/seed_users.py
uvicorn app.main:app --reload --port 8000
```

Serve the UI with a static server **only if** you point `window.CAMPUS_COPILOT_API_BASE` at the API. A bare `python -m http.server` on port 5500 will not proxy `/auth` and login will fail with Method Not Allowed. Prefer Docker on port 8080.

## Environment variables

Copy `.env.example` to `.env`. Do not commit `.env`.

Required for live RAG:

- `GEMINI_API_KEY`
- `JWT_SECRET` (replace the placeholder)

Also used: `USE_MOCK_LLM`, `GEMINI_EMBEDDING_MODEL`, `GEMINI_GENERATION_MODEL`, `JWT_EXPIRE_MINUTES`, `DATABASE_PATH`, `DOCUMENTS_DIR`, `CHUNK_SIZE`, `CHUNK_OVERLAP`, `TOP_K`, `CONFIDENCE_THRESHOLD`, `CORS_ORIGINS`. Optional: `INITIAL_ADMIN_PASSWORD` (required only when `scripts/seed_users.py` creates the first admin), `CAMPUS_ADMIN_USERNAME`, `CAMPUS_ADMIN_FULL_NAME`, `TESSERACT_CMD` for host OCR.

## Docker startup

From the repository root (the directory that contains `docker-compose.yml`):

```bash
cp .env.example .env
# Edit .env: GEMINI_API_KEY, JWT_SECRET, USE_MOCK_LLM=false

# Persistent files must exist on the host before the first start.
mkdir -p deploy/data/uploaded_documents
# Use an existing SQLite file, or create an empty one that init_db will migrate:
#   (Windows)  New-Item deploy/data/campus_copilot.db -ItemType File
#   (Unix)     touch deploy/data/campus_copilot.db

docker compose up -d --build
```

Check services:

```bash
docker compose ps
```

View logs:

```bash
docker compose logs -f
```

Stop services (keeps bind-mounted data):

```bash
docker compose down
```

**Do not run `docker compose down -v` for normal work.** This stack uses host bind mounts under `deploy/data/`, but `-v` removes named volumes and is unsafe if volumes are added later. Persistent storage is required for SQLite and uploaded documents; image layers are not a backup.

## How to access the application

- UI: [http://localhost:8080/](http://localhost:8080/)
- Health (via Nginx): [http://localhost:8080/health](http://localhost:8080/health)

Student sign-in uses enrollment number. Admin sign-in is on the “Admin sign in” panel. Accounts are those already in your local database (or created with the provisioning template). This repository does **not** publish live user passwords.

## Testing

From `backend/` with the project virtualenv:

```bash
python -m unittest discover -s tests -v
```

Tests use a temporary SQLite file and mock Gemini. They do not touch `deploy/data/campus_copilot.db`.

## Backup and restore

Docker bind mounts are not backups. Copy data out before upgrades.

1. `docker compose stop backend`
2. Copy `deploy/data/campus_copilot.db` with SQLite’s backup API and copy `deploy/data/uploaded_documents/`
3. Store copies under `deploy/backups/` (gitignored)
4. Restore by replacing those two paths and running `docker compose up -d`

See `deploy/README-DOCKER.md` for PowerShell examples.

## Known limitations

- **OCR is not enabled in the Docker image.** Tesseract is optional on the host; scanned PDFs without extractable text are not indexed.
- SQLite is intended for a **single backend instance**.
- Gemini usage is subject to provider quotas and model availability.
- Successful password changes **do not revoke** JWTs issued before the change; tokens remain valid until expiry.
- `synthetic_v1` documents and questions are **fictional test data**.
- Production hosting still needs HTTPS, a strong `JWT_SECRET`, outbound Gemini access, and durable disks for the database and uploads.
- Forgot-password / email OTP is not implemented (`POST /auth/password/forgot` returns 501).

## Future improvements

- JWT revocation or password-version claims after password change
- SMTP-backed password recovery with rate limits
- HTTPS and hardened secrets for a public host
- Optional OCR in the container image if scanned circulars become a requirement
- Annotated `university_v1` evaluation pack for a real corpus

## Project folder structure

```
Campus-Copilot/
├── backend/
│   ├── app/                    FastAPI app, RAG, auth, evaluation
│   ├── tests/                  unittest suite
│   ├── scripts/                seed, ingest, evaluate, provision template
│   ├── evaluation/             packs (synthetic_v1, university_v1)
│   ├── seed_data/              fictional campus fixtures (safe to publish)
│   ├── docs/                   operator notes (re-embed, data cleanup)
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .dockerignore
├── frontend/
│   ├── index.html
│   ├── app.js
│   ├── styles.css
│   ├── calendar.js
│   ├── eval-dashboard.js
│   ├── assets/
│   ├── Dockerfile
│   ├── nginx.conf
│   └── .dockerignore
├── deploy/
│   └── README-DOCKER.md
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
```

The nested folder `campus_copilot_project/` is an older duplicate of the tree and is **not** part of the release. Local `.env` files, `*.db`, `deploy/data/`, `deploy/backups/`, virtualenvs and uploaded originals stay on disk but are excluded from Git.
