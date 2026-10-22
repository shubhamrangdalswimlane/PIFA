# PIFA — Service Contracts

Single source of truth for the JSON shapes exchanged between the SPA (`web/`), the API (`pifa_api/`, served at `/api` on Vercel), the Drools rules service (`rules/`) and the file service (`files-svc/`).

## Common values

- Regions (fixed order): `North`, `East`, `West`, `South`.
- Roles: `SALES_MANAGER`, `REGIONAL_MANAGER`, `PLANNER`, `HEAD_OF_SALES`, `ADMIN`.
- Stages: `1 FORECAST_INPUT`, `2 REGIONAL_REVIEW`, `3 PLANNING`, `4 REGIONAL_CHANGE`, `5 FINAL_APPROVAL`, `6 PUBLISHED`.
- Quantity maps are `{ "<productId>": qty }`; a missing product means 0.
- Timestamps are ISO-8601 UTC strings.
- Errors: `{"detail": "message"}` or, for rule/file failures, `{"detail": {"message": "...", "violations": [Violation], "errors": [RowError]}}`.
  - `401` no/invalid token, `403` role or region not allowed, `409` wrong stage/status, `422` validation or rule violation, `503` dependency (rules/files) unavailable.
- `Violation` = `{"ruleId": "R-ALLOC-02", "product": "Model A", "region": "North" | null, "message": "..."}`.
- `RowError` = `{"row": 3, "message": "..."}`.

---

## 1. Public API (`/api`, Bearer = Keycloak access token from client `printer-web`)

### Identity and cycle

`GET /api/me`
```json
{"username": "rm.north", "name": "RM North", "role": "REGIONAL_MANAGER", "region": "North", "claims": {"...": "raw token claims"}}
```

`GET /api/cycle`
```json
{
  "id": 1, "name": "Cycle 2026-10", "stage": 2, "stageKey": "REGIONAL_REVIEW",
  "forecast": {"North": {"v1": "submitted", "v2": "draft"}, "East": {"v1": "draft", "v2": null}, "West": {...}, "South": {...}},
  "allocation": {"v1": "approved", "v2": "draft", "final": null},
  "confirmations": {"North": {"by": "rm.north", "at": "2026-10-22T10:00:00Z"}, "East": null, "West": null, "South": null},
  "nextActor": "Regional Managers: East, South"
}
```
Forecast statuses: `draft | submitted | approved | rejected`. Allocation statuses: `draft | approved | published`.

`GET /api/products` → `[{"id": 1, "name": "LaserJet Pro M404"}]`

### Forecast

`GET /api/forecast` (Sales Manager gets only own region; everyone else gets all four)
```json
{
  "regions": ["North", "East", "West", "South"],
  "products": [{"id": 1, "name": "LaserJet Pro M404"}],
  "v1": {"North": {"1": 120}, "East": {...}},
  "v2": {"North": {"1": 110}, "East": null},
  "status": {"North": {"v1": "submitted", "v2": "draft"}, "East": {...}}
}
```
`v2[region]` is `null` until the region's V1 is submitted.

`PUT /api/forecast/{region}?version=1|2` body `{"changes": [{"productId": 1, "qty": 10}], "comment": "why"}` → `{"updated": 1}`
- V1: Sales Manager of that region; stage 1 or 2; V1 status `draft` or `rejected`.
- V2: Regional Manager of that region; stage 2; V1 `submitted`, V2 `draft`.

→ `{"updated": 1, "revision": 6}`. Every save that changes at least one line (cell edits, one Excel file, or a restore) creates the region's next **version** `V<n>` — an immutable snapshot of the whole region forecast. Numbers run per cycle and region across both roles (Sales Manager V1…V5, then the Regional Manager continues V6, V7…). `revision` is `null` when nothing changed.

`GET /api/forecast` also returns `status[region].v1Rev` / `v2Rev`: the version each working copy holds (Sales Manager working copy / Regional Manager revision), and `v1SubmittedRev`: the version the Sales Manager submitted.

The Sales Manager's working forecast is editable at **every stage** (cell edits, uploads, restores); each save is a new version.
- While the region is in review (submitted, stage 1–2), each new Sales Manager version becomes the submitted version immediately: the Regional Manager's revision restarts from it (their earlier revision stays in the history) and an approval is withdrawn (`v2` back to `draft`).
- From Planning (stage 3) on, Sales Manager edits stay in their working copy. For every other role, `v1` in `GET /api/forecast`, forecast V1 in exports, the summary and auto-allocation (basis 1) use the submitted version.
- After a rejection the Sales Manager edits and submits again.

The Regional Manager edits their region (`PUT ?version=2`) throughout stage 2, also after approving it; such an edit sets it back to `draft` so it is approved again.

`GET /api/forecast/{region}/revisions` (Sales Manager: own region) → newest first
```json
[{"revNo": 6, "label": "V6", "stage": 2, "source": "edit" | "upload" | "submit" | "restore", "fileName": "north_q4.xlsx" | null,
  "createdBy": "rm.north", "role": "REGIONAL_MANAGER", "comment": "...", "changed": 3, "total": 1240, "createdAt": "..."}]
```
`stage` 1 = Sales Manager, 2 = Regional Manager.

`GET /api/forecast/{region}/revisions/{revNo}` → the same object plus `"lines": {"<productId>": qty}`.

`POST /api/forecast/{region}/revisions/{revNo}/restore` `{"comment": "required"}` → `{"updated", "revision"}`. Copies that version into the caller's working copy (Sales Manager → their forecast, Regional Manager → their revision) as a new version; same permissions and stages as `PUT`. `409` if nothing would change.

`GET /api/export/forecast?region=North&rev=5` → that version as an `.xlsx` in the upload template layout.

`POST /api/forecast/{region}/submit` `{"comment": "optional"}` — Sales Manager own region. Makes the latest version the Sales Manager's final version (creating one if nothing was saved), locks it, and starts the Regional Manager's revision from it. Stage 1 → 2 when all 4 are submitted.

`POST /api/forecast/{region}/approve` `{"comment": "optional"}` — Regional Manager own region, stage 2. Stage 2 → 3 when all 4 V2 are approved.

`POST /api/forecast/{region}/reject` `{"comment": "required"}` — Regional Manager own region, stage 2. V1 → `rejected` (editable by its Sales Manager again), V2 → `rejected`.

### Inventory (Planner writes in stage 3; all roles except Sales Manager read)

`GET /api/inventory` → `{"snapshot": {"id": 3, "sourceFile": "inv.xlsx" | null, "uploadedBy": "planner", "createdAt": "..."} | null, "lines": {"1": 500}}`

`PUT /api/inventory` `{"changes": [{"productId": 1, "qty": 500}], "comment": "..."}` → `{"updated": 1}`

### Allocation

`GET /api/allocation` (Sales Manager: own region only)
```json
{
  "regions": ["North", "East", "West", "South"],
  "v1": {"North": {"1": 25}, ...} | null,
  "v2": {...} | null,
  "final": {...} | null,
  "status": {"v1": "approved", "v2": "draft", "final": null}
}
```

`POST /api/allocation/auto` `{"comment": "...", "basis": 2}` — Planner, stage 3. Runs Drools R-ALLOC-01 on forecast V`basis` (default 2) and inventory, writes Allocation V1 (draft). → `{"v1": {...}, "violations": []}`

`PUT /api/allocation/v1` `{"changes": [{"productId": 1, "region": "North", "qty": 30}], "comment": "..."}` — Planner, stage 3. → `{"updated": 1}`

`PUT /api/allocation/v1/{region}/{productId}` `{"qty": 30, "comment": "..."}` — single-cell form of the above.

`POST /api/allocation/submit` `{"comment": "optional"}` — Planner, stage 3. `422` with R-ALLOC-02 violations if any model exceeds inventory. Approves V1, copies it to V2, stage → 4.

`POST /api/allocation/confirm` `{"comment": "optional"}` — Regional Manager own region, stage 4. Stage → 5 when all 4 confirm.

`POST /api/allocation/approve` `{"comment": "optional"}` — Head of Sales, stage 5. Publishes V2 as `final`, transfers → `approved`, stage → 6, writes export to SFTP `/outbound`.

`POST /api/allocation/reject` `{"comment": "required"}` — Head of Sales, stage 5. Stage → 4, confirmations cleared.

### Transfers (stage 4)

`GET /api/transfers` → `[Transfer]`
```json
{"id": 7, "productId": 1, "product": "Model A", "fromRegion": "East", "toRegion": "North", "qty": 5, "comment": "...",
 "requestedBy": "rm.north", "requestedRegion": "North", "status": "pending", "createdAt": "..."}
```
Statuses: `pending | undone | approved`.

`POST /api/transfers` `{"productId": 1, "fromRegion": "East", "toRegion": "North", "qty": 5, "comment": "..."}` → `Transfer`. Regional Manager; any two regions. Applies to Allocation V2 immediately and clears all confirmations.

`POST /api/transfers/{id}/undo` `{"comment": "..."}` → `Transfer`. Only the requester, only while stage 4 and status `pending`.

Head of Sales decisions (stage 5, R-APPR-01). `Transfer` also carries `decidedBy`, `decidedAt`, `decisionComment`; statuses add `rejected`.
- `POST /api/transfers/{id}/approve` `{"comment": "optional"}` → `Transfer` (`approved`).
- `POST /api/transfers/{id}/reject` `{"comment": "required"}` → `Transfer` (`rejected`); its units move back in allocation V2. `409` if the receiving region no longer holds them.
- `POST /api/transfers/approve-all` `{"comment": "optional"}` → `{"approved": n}`.
- `POST /api/allocation/approve` approves any transfers still pending together with publishing.

### Summary (Head KPIs, any role except Sales Manager)

`GET /api/summary`
```json
{
  "forecastV1": 4000, "forecastV2": 3900, "inventory": 3500, "allocated": 3400, "transfersPending": 2,
  "byRegion": {"North": {"forecastV1": 1000, "forecastV2": 950, "allocationV1": 850, "allocationV2": 880, "final": null}, ...}
}
```

### Audit

`GET /api/audit?role=&entity=&region=&q=&limit=500` → `[AuditEntry]` (Sales Manager: own region only)
```json
{"id": 1, "ts": "...", "username": "sm.north", "role": "SALES_MANAGER", "region": "North", "entity": "forecast",
 "version": "V1", "productId": 1, "product": "Model A", "beforeQty": 0, "afterQty": 120, "comment": "...", "status": "draft"}
```
Entities: `forecast | inventory | allocation | transfer | approval | workflow | file`.

### Files (Excel)

`POST /api/files/{kind}?region=North` multipart `file` (.xlsx) + `comment` → `{"fileId": 4, "status": "processed", "path": "/files/processed/...", "applied": 20, "revision": 6 | null, "message": "Saved as version V6"}`

Uploads work at **every stage** for the Sales Manager and the Planner. Regional Managers cannot upload (`403`); they revise on the dashboard.
- `kind=forecast`: columns `Product Name`, `Forecast Quantity` (or `Quantity`). Sales Manager, own `region`. Always applied to the Sales Manager's working forecast as the next version, at any stage.
- `kind=inventory`: `Product Name`, `Available Inventory`. Planner, any stage (cell edits stay stage 3). Unknown products are created. Allocation submit and final approval re-check R-ALLOC-02.
- `kind=allocation`: `Product Name`, `North`, `East`, `West`, `South`. Planner. Applied to allocation V1 while it is a draft (stages 1–3); once V1 is approved the file is validated and stored but not applied (`applied: 0`, explained in `message`).
- Rejected files: `422 {"detail": {"message": "...", "errors": [RowError]}}`.

`GET /api/files` → `[{"id", "path", "kind", "status", "message", "uploadedBy", "receivedAt"}]` (Planner, Head, Admin)

`GET /api/export/{kind}?version=1|2|final` kinds `forecast | inventory | allocation | audit` → `.xlsx` download (copy written to SFTP `/outbound`).

### Admin

`GET /api/admin/users` → `[{"username", "name", "email", "role", "region", "enabled"}]` (Admin, from Keycloak)

`POST /api/admin/stage` `{"action": "advance" | "reset", "comment": "required"}` → cycle (same shape as `GET /api/cycle`). `advance` cannot go 5 → 6 (only Head approves). `reset` starts a new empty cycle at stage 1.

`GET /api/admin/health` → `{"api": Health, "database": Health, "keycloak": Health, "rules": Health, "files": Health, "sftp": Health}`, `Health = {"ok": true, "detail": "..."}`

`GET /api/rules/catalogue` → `[{"id": "R-FC-01", "package": "forecast", "description": "..."}]` (all roles)

`GET /api/config/rules` → `{"baselinePct": 25, "sharing": "UNMET_DEMAND" | "PROPORTIONAL"}`; `PUT /api/admin/rule-config` same body + `comment` (Admin).

---

## 2. Rules service (`rules/`, Render). Bearer = client-credentials token with `azp == printer-api-svc`.

`GET /health` (no auth) → `{"status": "UP"}`

`GET /rules/catalogue` → `[{"id", "package", "description"}]`

`POST /rules/forecast`
```json
{
  "changes": [{"entity": "forecast" | "inventory" | "allocation", "product": "Model A", "region": "North" | null, "qty": 12.0, "comment": "...", "isRevision": false}],
  "review": {"actorRole": "REGIONAL_MANAGER", "decision": "APPROVE" | "REJECT", "comment": "..."} | null
}
```
→ `{"violations": [Violation]}`. Rules: R-FC-01 (whole number ≥ 0), R-FC-02 (comment, and reason for revisions), R-FC-03 (review rejection needs a comment).

`POST /rules/allocation`
```json
{
  "mode": "ALLOCATE" | "VALIDATE",
  "config": {"baselinePct": 25, "sharing": "UNMET_DEMAND"},
  "models": [{"product": "Model A", "inventory": 100, "demand": {"North": 30, "East": 25, "West": 25, "South": 20}, "allocated": {"North": 25, "East": 25, "West": 25, "South": 25}}]
}
```
→ `{"allocations": [{"product": "Model A", "region": "North", "qty": 30}], "violations": [Violation]}`
- `ALLOCATE` (R-ALLOC-01): demand ≤ inventory → allocate demand, surplus unallocated. Otherwise with `UNMET_DEMAND`: baseline `floor(inventory × pct / 100)` per region capped at that region's demand, remainder shared in proportion to unmet demand (largest-remainder rounding, ties in region order, never above demand). With `PROPORTIONAL`: share inventory in proportion to demand (largest remainder). `allocated` is ignored.
- `VALIDATE` (R-ALLOC-02 + R-FC-01): sum of `allocated` per model ≤ inventory; every quantity whole and ≥ 0. `allocations` is empty.

`POST /rules/transfer` `{"transfer": {"product": "Model A", "fromRegion": "East", "toRegion": "North", "qty": 5, "sourceQty": 25, "comment": "..."}}` → `{"violations": [...]}` (R-XFER-01)

`POST /rules/approval` `{"request": {"actorRole": "HEAD_OF_SALES", "decision": "APPROVE" | "REJECT", "comment": "...", "stage": 5}}` → `{"violations": [...]}` (R-APPR-01, R-XFER-02: publishing only by Head of Sales at stage 5)

---

## 3. File service (`files-svc/`, Render). Bearer = client-credentials token with `azp == printer-api-svc` (or `printer-upstream` for `/upstream`).

`GET /health` (no auth) → `{"status": "UP", "sftp": {"ok": true, "detail": "..."}}`

`POST /ingest/{kind}` multipart `file`, form `uploadedBy` → stores in `/files/inbound/{kind}/`, validates and parses (sandbox: size, extension, zip magic bytes, no macros, row cap, values only), moves to `/files/processed/` or `/files/rejected/` (with a `.reason.txt`).
```json
{"status": "processed" | "rejected", "path": "/files/processed/20261022T100000_sm.north_forecast.xlsx", "filename": "forecast.xlsx",
 "rows": [{"row": 2, "product": "Model A", "values": {"qty": 10}}],
 "errors": [RowError]}
```
`values` keys: forecast/inventory → `qty`; allocation → `North`, `East`, `West`, `South`.

`POST /exports` `{"filename": "allocation_final.xlsx", "sheet": "Allocation", "columns": ["Product Name", "North"], "rows": [["Model A", 30]]}` → `.xlsx` bytes; copy at `/files/outbound/<timestamp>_<filename>`.

`POST /upstream/{kind}` multipart `file` (azp `printer-upstream`) → `{"path": "/files/inbound/{kind}/..."}`. The poller validates it later and reports to the API.

Poller → API: `POST /api/internal/ingest` (service token) `{"path", "kind", "status", "message", "uploadedBy": "upstream"}` → `{"id": 9}`.
