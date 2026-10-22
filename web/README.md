# PIFA web (React SPA)

Vite + React 18 + TypeScript (strict) single-page app for the Printer Inventory Forecasting & Regional Allocation POC. It calls the API at same-origin `/api` (contract: `../docs/API_CONTRACT.md` §1) and signs in with Keycloak (Authorization Code + PKCE, token in memory).

## Run locally

```bash
pnpm install
cp .env.example .env.local   # set VITE_KEYCLOAK_URL
pnpm dev                     # http://localhost:5173, proxies /api → http://localhost:8000
```

The Keycloak client `printer-web` must allow `http://localhost:5173/*` as a redirect URI and web origin.

| Script | What it does |
|---|---|
| `pnpm dev` | Vite dev server on port 5173 |
| `pnpm build` | `tsc -b && vite build` → `dist/` (static, served by Vercel) |
| `pnpm typecheck` | TypeScript only |
| `pnpm lint` | ESLint |
| `pnpm preview` | Serve the built `dist/` |

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `VITE_KEYCLOAK_URL` | — (required) | Keycloak base URL |
| `VITE_KEYCLOAK_REALM` | `printer-poc` | Realm |
| `VITE_KEYCLOAK_CLIENT` | `printer-web` | Public PKCE client |
| `VITE_API_BASE` | `/api` | API base path |

## Structure

- `src/auth/` — keycloak-js init (`login-required`, S256, no login iframe), `updateToken(30)` before every API call, role/region from `realm_access.roles` and the `region` claim.
- `src/api/` — typed client (`client.ts`, `types.ts`) and React Query hooks (`hooks.ts`). Every mutation refetches the cycle and all business queries.
- `src/components/` — layout + stage tracker + claims viewer, editable grid with comment modal, version switch, Excel upload/template/export, audit table, transfer list, read-only data views.
- `src/pages/` — one dashboard per role: `/sales`, `/regional`, `/planner`, `/head`, `/admin`. `/` redirects to the user's dashboard; other roles' routes are blocked.
- Excel: SheetJS (`xlsx` from the official CDN tarball) is lazy-loaded for template generation and the in-browser upload preview.
