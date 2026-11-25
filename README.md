# Campus Copilot

Campus Copilot is a campus assistant. Students and admins ask about circulars, fees, hostel rules, exams, and other uploaded documents. Answers come from retrieved passages and are cited. If the corpus is not confident, the assistant says so instead of guessing.

Current release: **v0.2**. The app is a FastAPI backend, a SQLite database, and a static frontend. Gemini does embeddings and answer generation. Open the UI at [http://localhost:8080/](http://localhost:8080/) when using Docker.

Do not commit `.env`, `*.db`, or `deploy/data/`. Those files hold the API key, passwords, and uploaded documents. Copy `.env.example` and put your own `GEMINI_API_KEY` and `JWT_SECRET` there.

## v0.1

- Student chat with citations and saved conversations
- Admin document upload, ingest, catalogue, supersede, and delete
- JWT login for admins and students, plus change-password
- No public self-registration
- Shared academic calendar
- Gemini embeddings with cosine retrieval and a confidence cutoff
- Evaluation dashboard
- Docker Compose stack (Nginx on port 8080, API inside the backend container)

## v0.2

- Hybrid search: Gemini cosine similarity plus SQLite FTS5 keyword search, fused with Reciprocal Rank Fusion. The confidence cutoff still uses the cosine score.
- OCR for scanned PDFs and images (Tesseract in the Docker backend)
- Document catalogue pagination and category filter
- In-app notifications for students: new or superseded notices, calendar changes, and deadline reminders. No email or SMS.
- Admin user management: create a student, hand off a one-time setup code, edit the profile, and deactivate the account. Deactivated accounts cannot keep using an old token.
- A generation timeout so a slow Gemini call does not hang the chat

There is still no email delivery. An admin copies the setup code to the student. Public signup stays off.

## Run locally with Docker

This is the setup that keeps the frontend and the API on the same address.

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and start it.
2. From the project folder, copy the example env file and edit it:

```powershell
copy .env.example .env
```

Set `GEMINI_API_KEY` to your real key, set `JWT_SECRET` to a long random string, and leave `USE_MOCK_LLM=false`. Keep `GEMINI_EMBEDDING_MODEL=models/gemini-embedding-001` once documents have been embedded with that model. If the generation model in the example is out of quota for your key, set `GEMINI_GENERATION_MODEL` to one your key can call.

3. Create the data files, then start:

```powershell
New-Item -ItemType Directory -Force deploy\data\uploaded_documents
if (-not (Test-Path deploy\data\campus_copilot.db)) { New-Item deploy\data\campus_copilot.db -ItemType File }
docker compose up -d --build
```

4. Open [http://localhost:8080/](http://localhost:8080/) and hard-refresh once. [http://localhost:8080/health](http://localhost:8080/health) should show `"mock_mode": false`.

`docker compose down` stops the containers and keeps `deploy\data`. Do not use `docker compose down -v`.

The first admin is not created by Compose. With the stack stopped, from `backend` you can run `python scripts/seed_users.py` against `deploy\data\campus_copilot.db` after setting `INITIAL_ADMIN_PASSWORD` in the shell. The script does not overwrite an existing user. After that, admins create students from **User Management** and share the one-time setup code.

## Run the API without Docker

Requires Python 3.12. OCR on the host also needs [Tesseract](https://github.com/tesseract-ocr/tesseract) if you want scanned files indexed.

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Edit `backend\.env`: real `GEMINI_API_KEY`, a real `JWT_SECRET`, `USE_MOCK_LLM=false`, `DATABASE_PATH=./campus_copilot.db`, and `DOCUMENTS_DIR=./uploaded_documents`.

```powershell
$env:INITIAL_ADMIN_PASSWORD = "choose-a-password"
python scripts/seed_users.py
uvicorn app.main:app --reload --port 8000
```

On macOS or Linux, activate with `source .venv/bin/activate` and use `export INITIAL_ADMIN_PASSWORD=...`.

Opening `frontend/index.html` as a file, or with `python -m http.server`, will not proxy `/auth` and login will fail. Prefer Docker on port 8080. If you serve the static files yourself, set `window.CAMPUS_COPILOT_API_BASE = "http://localhost:8000"` before `app.js` loads, and set `CORS_ORIGINS` to that page’s origin.

## Tests

From `backend` with the virtualenv active:

```powershell
python -m unittest discover -s tests -v
```

Tests use a temporary database and mock Gemini. They do not touch your real `.env` key or `deploy\data`.
