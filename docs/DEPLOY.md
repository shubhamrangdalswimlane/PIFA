# Deploying PIFA (Render + Vercel)

Render runs what Vercel cannot: Keycloak, files-svc, the SFTP server and PostgreSQL.
Vercel runs the React app and the FastAPI API (`/api`), which includes the Python business rules. Both deploy from the GitHub repo and redeploy on every push to `main`.

```
Browser ──► Vercel: React app + /api (FastAPI + rules) ──► Render: Postgres, Keycloak, files-svc ──► SFTP (private)
```

Allow about 30–45 minutes. Render services used here are paid instances (free ones sleep and Keycloak needs ≥ 1 GB RAM).

---

## 0. Before you start

1. The code is on GitHub (`main`). Render and Vercel both need access to the repo.
2. Pick the names now, because each platform needs the other's URL:
   - Vercel project name, e.g. `pifa` → `https://pifa.vercel.app` (if the name is taken Vercel adds a suffix; check after step 3 and fix as in step 4).
   - Render service names come from `render.yaml`: `pifa-keycloak`, `pifa-files` → `https://<name>.onrender.com` (Render may add a suffix if a name is taken).
3. Create the secrets (keep them in a password manager, not in Git):

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```
Run it three times: **SVC secret**, **UPSTREAM secret**, and the **seed password** for the 11 users (or choose your own strong password).

```bash
.venv/Scripts/python scripts/dev_keys.py
```
This prints the SFTP **public key** and writes the **private key** to `.env` as `SFTP_PRIVATE_KEY="..."` (one line with `\n`). Copy both values.

## 1. Render: database, Keycloak, files-svc, SFTP

1. Render Dashboard → **New → Blueprint** → connect GitHub → choose the PIFA repo. Render reads `render.yaml`.
2. Fill in the values it asks for (`sync: false` entries):

| Service | Variable | Value |
|---|---|---|
| pifa-keycloak | `KC_HOSTNAME` | `https://pifa-keycloak.onrender.com` |
| pifa-keycloak | `PIFA_WEB_ORIGIN` | `https://pifa.vercel.app` (no trailing slash) |
| pifa-keycloak | `PIFA_SEED_PASSWORD` | seed password |
| pifa-keycloak | `PIFA_SVC_CLIENT_SECRET` | SVC secret |
| pifa-keycloak | `PIFA_UPSTREAM_CLIENT_SECRET` | UPSTREAM secret |
| pifa-files | `KEYCLOAK_ISSUER` | `https://pifa-keycloak.onrender.com/realms/printer-poc` |
| pifa-files | `SVC_CLIENT_SECRET` | SVC secret (same value) |
| pifa-files | `SFTP_PRIVATE_KEY` | private key from `.env` (the part inside the quotes) |
| pifa-files | `SFTP_HOST_KEY` | leave empty for now (optional pinning, see below) |
| pifa-files | `API_URL` | `https://pifa.vercel.app` |
| pifa-sftp | `SFTP_PUBLIC_KEY` | public key line (`ssh-ed25519 AAAA… files-svc`) |

3. Click **Apply**. The first Keycloak build takes several minutes.
4. When everything is live, check in a browser:
   - `https://pifa-keycloak.onrender.com/realms/printer-poc/.well-known/openid-configuration` → JSON
   - `https://pifa-files.onrender.com/health` → `"sftp":{"ok":true,...}`
5. Copy the database URL for Vercel: **pifa-db → Connect → External Database URL**.

If Render gave a service a different URL than you entered, update the variables that point to it, then **Manual Deploy → Deploy latest commit** on the affected services.

## 2. Vercel: React app + API

1. Vercel → **Add New → Project** → import the PIFA repo.
   - Root Directory: repo root (`./`). Framework preset: **Other** (`vercel.json` sets install, build, output and the `/api` function).
2. **Environment Variables** (Production, and Preview if you use previews):

| Variable | Value |
|---|---|
| `DATABASE_URL` | Render **External** Database URL + `?sslmode=require` |
| `KEYCLOAK_ISSUER` | `https://pifa-keycloak.onrender.com/realms/printer-poc` |
| `SVC_CLIENT_SECRET` | SVC secret |
| `FILES_URL` | `https://pifa-files.onrender.com` |
| `ALLOWED_ORIGINS` | `https://pifa.vercel.app` |
| `VITE_KEYCLOAK_URL` | `https://pifa-keycloak.onrender.com` |

   `VITE_*` values are baked into the app at build time: after changing one, redeploy.
3. **Deploy.** The API creates its tables on the first request (migrations run automatically).

## 3. Check the live app

1. Open `https://pifa.vercel.app` → you are sent to Keycloak → sign in as `admin` with the seed password.
2. **Admin → Health**: API, Database, Keycloak, Rules, Files and SFTP should all be green.
3. Sign in as `sm.north`, upload `data_synthetic/forecast_North.xlsx`, and continue the cycle as usual.

## 4. If the Vercel URL is not the one you planned

Keycloak imports the realm **only on its first start**, so changing `PIFA_WEB_ORIGIN` later has no effect. Fix it in the Keycloak admin console instead:

1. `https://pifa-keycloak.onrender.com/admin` → user `kcadmin`, password = `KC_BOOTSTRAP_ADMIN_PASSWORD` (Render → pifa-keycloak → Environment).
2. Realm **printer-poc → Clients → printer-web**: set **Valid redirect URIs** `https://<your-app>.vercel.app/*`, **Valid post logout redirect URIs** the same, **Web origins** `https://<your-app>.vercel.app`. Save.
3. Update `ALLOWED_ORIGINS` (Vercel) and `API_URL` (Render, pifa-files) and redeploy those.

Vercel **preview** deployments get their own URLs; add each one you want to log in from to the same three fields (Keycloak does not accept domain wildcards).

## 5. Optional hardening

- **Pin the SFTP host key:** Render → pifa-sftp → **Shell** → `cat /home/.hostkeys/ssh_host_ed25519_key.pub` → paste the first two parts (`ssh-ed25519 AAAA…`) into `SFTP_HOST_KEY` on pifa-files and redeploy.
- **Change seed passwords** after the first login (Keycloak admin → Users → Credentials), or let each user change it.
- Vercel's Hobby plan is for non-commercial use; use a Pro/Team plan for company use.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Keycloak page says "Invalid parameter: redirect_uri" | `printer-web` redirect URIs don't contain your Vercel URL (step 4). |
| API returns 401 "Invalid token … issuer" | `KEYCLOAK_ISSUER` differs from the token: must be exactly `https://…onrender.com/realms/printer-poc`, and `KC_HOSTNAME` must be the `https://` URL. |
| API returns 503 "File service" | pifa-files still deploying, or `SVC_CLIENT_SECRET` differs between Keycloak, Vercel and pifa-files. |
| Health shows Database red | `DATABASE_URL` is the internal URL or misses `?sslmode=require`. |
| Health shows SFTP red | Public key on pifa-sftp doesn't match the private key on pifa-files. |
| Sign-in loops back to the login page | `VITE_KEYCLOAK_URL` wrong or not redeployed after changing it. |
