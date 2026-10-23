# PIFA — Printer Inventory Forecasting & Regional Allocation

Governed workflow that turns regional printer forecasts into an approved, auditable inventory allocation.
See `docs/` for the PRD, architecture and the service contract (`docs/API_CONTRACT.md`), and `Phase.md` for the build plan.

## What runs where

| Part | Folder | Host |
|---|---|---|
| React SPA (Vite, TS, SheetJS, keycloak-js) | `web/` | Vercel (static) |
| FastAPI API at `/api`, incl. the business rules engine (`pifa_api/rules/`) | `pifa_api/` + `api/index.py` | Vercel (Python function) |
| Keycloak (realm `printer-poc`, 11 users) | `keycloak/` | Render web service |
| files-svc (SFTP gateway, Excel sandbox, poller) | `files-svc/` | Render web service |
| SFTP server (key-only, chrooted) | `sftp/` | Render private service + disk |
| PostgreSQL (Keycloak in `public`, app in schema `pifa`) | — | Render Postgres |

The API applies its SQL migrations (`pifa_api/migrations/`) automatically on cold start (advisory-locked).

**Month-year planning.** Each month-year (e.g. Nov 2026) runs the whole pipeline on its own: pick it in the **Month** selector in the header, or open a new one with **＋ Month**. Forecast versions, stages, inventory, allocation and history are per month. An Excel upload with a `Month` column fills several months at once (each month gets its own version); `Product_Name` headers work and new product names are added. Sample files: `data_synthetic/forecast_<Region>_monthly.xlsx` and `inventory_monthly.xlsx` (Nov 2026 – Jan 2027).

## Local development

Prerequisites: Docker, Python 3.12 + [uv](https://docs.astral.sh/uv/), Node 20+ with pnpm.

```bash
uv venv .venv --python 3.12 && uv pip install --python .venv -r requirements.txt uvicorn pytest ruff openpyxl paramiko
```
```bash
cp .env.example .env
```
```bash
.venv/Scripts/python scripts/dev_keys.py
```
```bash
docker compose up -d --build
```
```bash
.venv/Scripts/python -m uvicorn pifa_api.main:app --port 8000
```
```bash
cp web/.env.example web/.env.local && pnpm --dir web install && pnpm --dir web dev
```

Open http://localhost:5173 and sign in as `sm.north`, `sm.east`, `sm.west`, `sm.south`, `rm.north` … `rm.south`, `planner`, `head` or `admin`
(password = `PIFA_SEED_PASSWORD`, default `Pifa!2026`). Local ports: Keycloak 8080, files-svc 8082, Postgres 5432, API 8000.

### Tests

```bash
docker run -d --name pifa-test-pg -e POSTGRES_DB=pifa_test -e POSTGRES_USER=pifa -e POSTGRES_PASSWORD=pifa -p 5433:5432 postgres:16
```
```bash
.venv/Scripts/python -m pytest tests -q
```
```bash
pnpm --dir web build
```

- `tests/api`: full cycle incl. the PRD worked example (30/20/25/25), region isolation, mandatory comments, R-ALLOC-02 block, transfer undo, Head-only publish, admin override audit, append-only audit log. Runs against the real Python business rules.
- `tests/files_svc`: Excel validation, rejection with reason file, formula-safe export, upstream poller.
- `tests/rules`: every rule ID (pass + fail), the R-ALLOC-01 maths incl. rounding, and 5,000 randomised allocation checks.

## Deploy

Step-by-step guide with checks and troubleshooting: [docs/DEPLOY.md](docs/DEPLOY.md). Summary:

### 1. Render (Keycloak, files-svc, SFTP, Postgres)

1. Push this repo to GitHub.
2. Generate the SFTP key pair: `python scripts/dev_keys.py` (prints the public key; the private key is in `.env`).
3. Render Dashboard → **New → Blueprint** → select the repo (`render.yaml`). Fill the prompted values:

| Service | Variable | Value |
|---|---|---|
| pifa-keycloak | `KC_HOSTNAME` | `https://pifa-keycloak.onrender.com` (the service URL) |
| pifa-keycloak | `PIFA_WEB_ORIGIN` | `https://<your-app>.vercel.app` |
| pifa-keycloak | `PIFA_SEED_PASSWORD` | initial password for the 11 users |
| pifa-keycloak, pifa-files | `PIFA_SVC_CLIENT_SECRET` / `SVC_CLIENT_SECRET` | same random secret |
| pifa-keycloak | `PIFA_UPSTREAM_CLIENT_SECRET` | random secret for upstream file drops |
| pifa-files | `KEYCLOAK_ISSUER` | `https://pifa-keycloak.onrender.com/realms/printer-poc` |
| pifa-files | `SFTP_PRIVATE_KEY` | private key (single line with `\n`) |
| pifa-files | `API_URL` | `https://<your-app>.vercel.app` |
| pifa-sftp | `SFTP_PUBLIC_KEY` | public key line |

Optional: pin the SFTP host key by copying `/home/.hostkeys/ssh_host_ed25519_key.pub` from the pifa-sftp shell into `SFTP_HOST_KEY` on pifa-files.

The realm is imported only on Keycloak's first start. Changing `PIFA_*` values later means editing the realm in the Keycloak admin console.

### 2. Vercel (SPA + API)

Import the repo in Vercel (root directory = repo root; `vercel.json` sets the build). Set the function region to match Render (`iad1` for Virginia) and add:

| Variable | Value |
|---|---|
| `DATABASE_URL` | Render Postgres **external** URL + `?sslmode=require` |
| `KEYCLOAK_ISSUER` | `https://pifa-keycloak.onrender.com/realms/printer-poc` |
| `SVC_CLIENT_SECRET` | same as `PIFA_SVC_CLIENT_SECRET` |
| `FILES_URL` | `https://pifa-files.onrender.com` |
| `ALLOWED_ORIGINS` | `https://<your-app>.vercel.app` |
| `VITE_KEYCLOAK_URL` | `https://pifa-keycloak.onrender.com` |

Keycloak redirect URIs cannot use domain wildcards: add each Vercel preview URL you want to log in from to the `printer-web` client.

## Known limits (POC)

- SFTP is reachable only inside Render; upstream systems drop files over HTTPS (`POST /upstream/{kind}` on files-svc with a `printer-upstream` token). The poller validates them and records them in the file log; applying an upstream file to the plan is still a Planner action.
- One active cycle at a time; Admin "reset" starts a new one.
- Vercel caps request bodies at 4.5 MB; uploads are limited to 4 MB.
