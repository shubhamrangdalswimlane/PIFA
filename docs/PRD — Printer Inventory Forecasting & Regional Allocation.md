# PRD — Printer Inventory Forecasting & Regional Allocation

Oct 22, 2026 · @Shubham Rangdal

## 1. Overview

This product replaces manual spreadsheet changes with one governed workflow that turns regional printer forecasts into an approved, auditable inventory allocation. Forecasts may not match regional sales needs, while limited printer inventory must be shared fairly. Manual changes make approvals and stock movements hard to track.

**Solution.** Sales Managers analyze sales history and prepare model-wise forecasts for North, East, West and South. Regional Managers review and revise those forecasts, and Planning reconciles the revised demand with available inventory. The Head of Sales approves only final allocation changes.

**Key control.** Head of Sales approval is mandatory for final allocation changes. Every approved allocation must respect inventory limits and keep an audit trail.

**Status.** This PRD covers the POC. A clickable static mock (`index.html`) and `POC_Architecture.md` already exist.

## 2. Goals, non-goals and success metrics

The POC succeeds if one full planning cycle runs end to end with every change traceable to a person, a reason and a version.

**Goals**

- Give each region one place to enter and revise model-wise forecasts, with a reason for every change.
- Allocate limited inventory from the revised demand, never above available stock.
- Let Regional Managers rebalance units between regions, with Head of Sales approving before publication.
- Keep a complete audit trail (who, what, before/after, reason, time, approval status).

**Non-goals (POC)**

- Notifications, corporate SSO, high availability, multi-cycle history.
- Forecasting algorithms; forecasts are entered by people.
- Order, shipping or warehouse execution.

**Success metrics (targets to confirm)**

| Metric | Target |
| --- | --- |
| Cycle completed in the POC without spreadsheets | 1 full cycle, all 5 roles |
| Edits with a recorded comment | 100% |
| Published allocations exceeding inventory | 0 |
| Published allocations without Head approval | 0 |
| Time from forecast submission to approved allocation | To be baselined with the business |

## 3. Users, roles and data visibility

There are 11 role holders across five roles, and visibility is enforced in the API from the JWT role and region claims, not only in the UI.

| Role | Users | Sees | Can change |
| --- | --- | --- | --- |
| Sales Manager | 4 (one per region) | Own region only | Own region forecast V1 |
| Regional Manager | 4 (one per region) | All four regions | Own region forecast V2; transfers between regions |
| Planner | 1 | All regions and inventory | Inventory; allocation V1 |
| Head of Sales | 1 | All data | Approve or reject final allocation only |
| Admin | 1 | All data, users, audit | Workflow controls; read-only on business data |

## 4. Workflow and versions

Work moves through five stages, and only the last one needs Head of Sales approval. Forecasts go from Regional Managers straight to Planning.

| # | Stage | Actor | Exit condition | Output |
| --- | --- | --- | --- | --- |
| 1 | Forecast input | Sales Manager | All 4 regions submit | Forecast V1 |
| 2 | Regional review | Regional Manager | All 4 regions approve | Forecast V2 with reasons |
| 3 | Planning | Planner | Planner approves allocation | Inventory snapshot, Allocation V1 |
| 4 | Regional change | Regional Manager | All 4 regions confirm | Allocation V2 (transfers) |
| 5 | Final approval | Head of Sales | Approve (publish) or reject | Published allocation |

A rejection by the Head returns the cycle to stage 4 with a mandatory comment and clears the regional confirmations.

**Versions.** Forecast V1 is the Sales Manager's submission and V2 is the Regional Manager's revision. Allocation V1 is the Planner's allocation and V2 is the result after regional transfers. Every dashboard can switch between V1 and V2 and shows the V2 difference against V1.

**Worked example (Printer Model A, 100 units).** Initial allocation is 25 per region. A proposed transfer moves 5 units from East to North, giving North 30, East 20, West 25 and South 25 (still 100). It is not published until Head of Sales approves.

## 5. Functional requirements

Requirements are grouped by dashboard. IDs are stable so tests and tickets can reference them.

**Common to all dashboards**

- FR-C1: V1 / V2 version switch with V2-vs-V1 differences shown.
- FR-C2: Cell-level edit where the role may edit; a non-empty comment is required for every edit.
- FR-C3: Excel upload with a Product Name column (with a before/after preview and required comment) and Excel export.
- FR-C4: Stage tracker showing the five workflow steps and who acts next.
- FR-C5: Role-based sign-in via Keycloak; the UI shows only screens allowed by the role.

**Sales Manager dashboard**

- FR-S1: See and edit only own region's forecast V1 by product (other regions are never returned).
- FR-S2: Upload and download a forecast template (Product Name plus quantity).
- FR-S3: Submit the region forecast, which locks V1.
- FR-S4: View V2 (Regional Manager revisions) and own-region allocation as read-only.
- FR-S5: Change history for own region.

**Regional Manager dashboard**

- FR-R1: See all four regions side by side; own region highlighted.
- FR-R2: Edit only own region in forecast V2, with a reason per change; approve own region forecast.
- FR-R3: Transfer box: choose product, region to reduce, region to increase, units and comment, with a live before/after preview (example: North to East, 5 units).
- FR-R4: Undo own transfer while stage 4 is open; list of transfers with who, when, comment and status.
- FR-R5: See allocation V1 and V2 with inventory and balance; confirm own review.

**Planner dashboard**

- FR-P1: Upload and edit inventory (Product Name plus available inventory), each edit commented.
- FR-P2: Demand vs inventory per product, flagging constrained products.
- FR-P3: Auto-allocate from the revised forecast; edit any cell with a comment; upload allocation by region.
- FR-P4: Block approval if any product's allocation exceeds inventory; approve to send to Regional Managers.

**Head of Sales dashboard**

- FR-H1: Read-only view of all forecasts and allocations (V1 / V2).
- FR-H2: KPI cards (forecast V1, forecast V2, inventory, allocated, transfers pending) and region comparison.
- FR-H3: Review transfers and approve (publish) or reject; rejection needs a comment.
- FR-H4: Full audit trail with export.

**Admin dashboard**

- FR-A1: View users, roles and region mapping.
- FR-A2: Workflow stage control (advance and reset) with every override logged.
- FR-A3: Integration health for Keycloak, SFTP, Drools and the API.
- FR-A4: Read-only view of all data and a filterable audit dashboard (role, entity, free text) with export.

## 6. Business rules and audit

Seven rules run in Drools before any write that changes business data.

| ID | Rule |
| --- | --- |
| R-FC-01 | Forecast quantity is a whole number of 0 or more. |
| R-FC-02 | Every change to forecast, inventory or allocation needs a comment. |
| R-ALLOC-01 | If revised demand is at most inventory, allocate the demand. Otherwise allocate in proportion to revised demand. The 25% per-region split is only a starting baseline; demand and approved business rules set the final split. |
| R-ALLOC-02 | Total allocated per model must not exceed available inventory. |
| R-XFER-01 | A transfer moves units between two different regions, cannot exceed the source region's allocation, and needs a comment. |
| R-XFER-02 | A transfer cannot be published until Head of Sales approves. |
| R-APPR-01 | Only Head of Sales approves or rejects the final allocation; rejection needs a comment and returns to stage 4. |

**Audit.** Each change records who changed it, the reason, before and after quantities, timestamps and approval status, by region and model. The audit log is append-only and exportable.

## 7. Non-functional requirements and technology

The stack is fixed for the POC: React, Python, Keycloak with JWT, Drools and SFTP. Details are in `POC_Architecture.md`.

| Area | Choice or requirement |
| --- | --- |
| Frontend | React (Vite, TypeScript); SheetJS for Excel preview |
| API | Python 3.12, FastAPI; validates the Keycloak JWT via JWKS |
| Identity | Keycloak realm with roles SALES\_MANAGER, REGIONAL\_MANAGER, PLANNER, HEAD\_OF\_SALES, ADMIN and a `region` claim |
| Rules | Drools KIE Server (JVM) called by the API over REST |
| Files | SFTP for Excel in and out: `/inbound`, `/processed`, `/rejected`, `/outbound`; key-based access |
| Database | PostgreSQL; append-only audit table |
| Security | Region scoping enforced in the API; TLS everywhere; 15-minute access tokens; Excel validated and parsed in a sandboxed worker |
| Performance | Grids of up to about 200 products load in under 2 seconds (target to confirm) |
| Usability | Desktop browsers; tables scroll on narrow screens |

## 8. POC scope, risks and open questions

**Delivered so far.** A static, clickable mock of all five dashboards (simulated sign-in, in-browser data) and the architecture document. Next is the working build on the fixed stack.

**Proposed build phases (durations to be agreed)**

1. Platform: Keycloak realm and roles, FastAPI skeleton with JWT and region scoping, PostgreSQL schema, SFTP.
2. Forecast flow: Sales Manager and Regional Manager screens, Excel upload, audit log.
3. Allocation flow: Planner screens, Drools allocation and transfer rules, transfer box.
4. Approval and admin: Head approval, Admin audit dashboard, end-to-end test of one full cycle.

**Risks**

| Risk | Mitigation |
| --- | --- |
| Drools runs on the JVM, adding a service to a Python stack | Run KIE Server as a separate container; call it over REST |
| Allocation weighting rules not yet defined | Ship proportional-to-demand; make rules configurable in Drools |
| Messy Excel inputs | Template download, preview before apply, rejected-file folder with reasons |
| One region blocks the whole cycle by not submitting | Admin stage override, logged in the audit trail |

**Open questions**

- [ ] Should Sales Managers enter forecasts (assumed) or only view them?
- [ ] Can a Regional Manager transfer between any two regions, or only involving their own?
- [ ] What business rules replace the 25% baseline when stock is constrained?
- [ ] Is a Regional Manager's rejected-forecast path needed, or only approval?
- [ ] Should surplus stock (demand below inventory) stay unallocated or be distributed?
- [ ] Expected products per cycle and file formats from upstream systems?
