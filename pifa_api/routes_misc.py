"""Identity, cycle, summary, audit, Excel files, exports, Admin and internal endpoints."""

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from psycopg import Connection
from pydantic import BaseModel, Field

from . import clients, db, exports, period, store, workflow
from . import rules as business_rules
from .auth import EVERYONE, READ_ALL, User, current_user, require_role, service_caller
from .config import get_settings
from .db import get_db
from .domain import ADMIN, HEAD, PLANNER, REGIONS, SM, STAGES, forbidden, invalid, require_comment
from .routes_workflow import (
    allocation_v1_open,
    apply_allocation_changes,
    apply_forecast_changes,
    apply_inventory_changes,
)

router = APIRouter(prefix="/api")
MAX_UPLOAD = 4 * 1024 * 1024  # Vercel request bodies are capped at 4.5 MB


@router.get("/me")
def me(user: User = Depends(current_user)):
    """Return who the caller is, as read from their token.

    Args:
        user: signed-in caller (from the JWT).

    Returns:
        {"username", "name", "role", "region", "claims"}.
    """
    return {"username": user.username, "name": user.name, "role": user.role, "region": user.region, "claims": user.claims}


@router.get("/cycle")
def get_cycle(user: User = Depends(current_user), conn: Connection = Depends(get_db)):
    """Return the planning cycle state of the selected month.

    Args:
        user: signed-in caller (from the JWT).
        conn: database connection for this request.

    Returns:
        The cycle view (see workflow.cycle_view).
    """
    return workflow.cycle_view(conn)


class PeriodBody(BaseModel):
    period: str
    comment: str = ""


def _period_json(c: dict) -> dict:
    """Shape a cycle row as a period entry for the API.

    Args:
        c: cycle row.

    Returns:
        {"period", "label", "cycleId", "name", "stage", "stageKey"}.
    """
    return {"period": period.key(c["period"]), "label": period.label(c["period"]), "cycleId": c["id"], "name": c["name"],
            "stage": c["stage"], "stageKey": STAGES[c["stage"]]}


@router.get("/periods")
def list_periods(user: User = Depends(current_user), conn: Connection = Depends(get_db)):
    """Every month-year with its current cycle and stage, oldest first.

    Args:
        user: signed-in caller (from the JWT).
        conn: database connection for this request.

    Returns:
        list of {"period", "label", "cycleId", "name", "stage", "stageKey"}.
    """
    return [_period_json(c) for c in store.periods(conn)]


@router.post("/periods")
def create_period(body: PeriodBody, user: User = Depends(require_role(SM, PLANNER, ADMIN)), conn: Connection = Depends(get_db)):
    """Open a month-year for planning (stage 1). Returns the existing one when it is already open.

    Args:
        body: {"period": month-year text such as "2026-11" or "Nov-2026", "comment": optional reason}.
        user: signed-in caller (from the JWT); Sales Manager, Planner or Admin.
        conn: database connection for this request.

    Returns:
        {"period", "label", "cycleId", "name", "stage", "stageKey"} of the month's cycle.

    Raises:
        HTTPException: 422 when the period is not a valid month-year.
    """
    try:
        p = period.parse(body.period)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    existed = store.cycle_for_period(conn, p) is not None
    cycle = store.ensure_period_cycle(conn, p)
    if not existed:
        store.audit(conn, user, "workflow", cycle_id=cycle["id"], version=period.key(p),
                    comment=body.comment.strip() or f"Opened {period.label(p)} for planning", status="period")
    return _period_json(cycle)


@router.get("/products")
def get_products(user: User = Depends(current_user), conn: Connection = Depends(get_db)):
    """List all printer models.

    Args:
        user: signed-in caller (from the JWT).
        conn: database connection for this request.

    Returns:
        list of {"id", "name"}.
    """
    return store.products(conn)


@router.get("/summary")
def summary(user: User = Depends(require_role(*READ_ALL)), conn: Connection = Depends(get_db)):
    """Dashboard totals for the selected month: forecast V1/V2, inventory, allocated units and pending transfers.

    Args:
        user: signed-in caller (from the JWT); Regional Manager, Planner, Head of Sales or Admin.
        conn: database connection for this request.

    Returns:
        {"forecastV1", "forecastV2", "inventory", "allocated", "transfersPending",
        "byRegion": {region: {"forecastV1", "forecastV2", "allocationV1", "allocationV2", "final"}}};
        an allocation total is None when that version does not exist yet.
    """
    cid = store.current_cycle(conn)["id"]
    f1, f2 = store.forecast_totals(conn, cid, 1), store.forecast_totals(conn, cid, 2)
    snap = store.inventory_snapshot(conn, cid)
    allocs = {}
    for key in ("1", "2", "final"):
        av = store.allocation_version(conn, cid, key)
        allocs[key] = store.allocation_lines(conn, av["id"]) if av else None

    def total(m: dict | None, region: str) -> int | None:
        """Sum one region's units in an allocation map.

        Args:
            m: allocation map {region: {product_id: qty}}, or None when that version does not exist.
            region: region name.

        Returns:
            Total units, or None when m is None.
        """
        return sum(m[region].values()) if m is not None else None

    latest = allocs["final"] or allocs["2"] or allocs["1"]
    pending = conn.execute(
        "SELECT count(*) AS n FROM transfer_request WHERE cycle_id = %s AND status = 'pending'", (cid,)
    ).fetchone()["n"]
    return {
        "forecastV1": sum(sum(m.values()) for m in f1.values()),
        "forecastV2": sum(sum(m.values()) for m in f2.values()),
        "inventory": sum(store.inventory_lines(conn, snap["id"] if snap else None).values()),
        "allocated": sum(total(latest, r) for r in REGIONS) if latest else 0,
        "transfersPending": pending,
        "byRegion": {
            r: {
                "forecastV1": sum(f1.get(r, {}).values()),
                "forecastV2": sum(f2.get(r, {}).values()),
                "allocationV1": total(allocs["1"], r),
                "allocationV2": total(allocs["2"], r),
                "final": total(allocs["final"], r),
            }
            for r in REGIONS
        },
    }


@router.get("/audit")
def audit(role: str | None = None, entity: str | None = None, region: str | None = None, q: str | None = None,
          month: str | None = None, limit: int = Query(500, ge=1, le=5000), user: User = Depends(require_role(*EVERYONE)),
          conn: Connection = Depends(get_db)):
    """`month`: omitted = selected month, "all" = every month, "2026-11" = that month.

    Returns the audit trail visible to the caller (Sales Manager, Regional Manager and Planner: own changes only).

    Args:
        role: only entries made by this role.
        entity: only entries about this entity.
        region: only entries for this region.
        q: free-text search over comment, username, product and status.
        month: month filter as described above.
        limit: maximum number of entries (1-5000).
        user: signed-in caller (from the JWT).
        conn: database connection for this request.

    Returns:
        list of audit entries, newest first (see store.audit_entries).

    Raises:
        HTTPException: 422 when `month` is not a valid month-year.
    """
    return store.audit_entries(conn, user, role=role, entity=entity, region=region, q=q, limit=limit, month=month)


# --- Excel files ---------------------------------------------------------------------------------

def _record_file(result: dict, kind: str, user: User, cycle_id: int, comment: str) -> int:
    """Committed on its own connection so rejected uploads stay on record.

    Writes a file_ingest row and an audit entry for an upload.

    Args:
        result: files-svc ingest result.
        kind: forecast, inventory or allocation.
        user: uploader.
        cycle_id: cycle the upload belongs to.
        comment: reason given for the upload.

    Returns:
        The new file_ingest id.
    """
    message = "; ".join(f"row {e['row']}: {e['message']}" for e in result.get("errors", [])[:20]) or "ok"
    with db.connect() as c:
        row = c.execute(
            "INSERT INTO file_ingest (path, kind, status, message, uploaded_by) VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (result.get("path", ""), kind, result["status"], message, user.username),
        ).fetchone()
        store.audit(c, user, "file", cycle_id=cycle_id, version=kind, comment=f"{result.get('filename')}: {comment}",
                    status=result["status"])
    return row["id"]


@router.post("/files/{kind}")
def upload_file(kind: str, file: UploadFile = File(...), comment: str = Form(""), region: str | None = Query(None),
                version: int | None = Query(None), user: User = Depends(require_role(SM, PLANNER)),
                conn: Connection = Depends(get_db)):
    """Excel upload, available to the Sales Manager (own forecast) and the Planner at every stage.

    Regional Managers do not upload; they revise forecasts on the dashboard.

    Args:
        kind: forecast, inventory or allocation.
        file: the .xlsx file.
        comment: required reason for the upload.
        region: forecast uploads only: the Sales Manager's own region.
        version: accepted for compatibility; not used.
        user: signed-in caller (from the JWT); Sales Manager or Planner.
        conn: database connection for this request.

    Returns:
        {"fileId", "status", "path", "applied": int, "revision": int | None,
        "periods": [{"period", "label", "applied", "revision", "message"}], "newProducts": [str], "message": str}.

    Raises:
        HTTPException: 404 for an unknown kind; 403 when the caller may not upload this kind or region;
            413 when the file is larger than 4 MB; 422 when the region or comment is missing, the file is rejected
            or a value breaks a business rule; 409 when allocation V1 is already approved.
    """
    if kind not in ("forecast", "inventory", "allocation"):
        raise HTTPException(404, f"Unknown file kind {kind}")
    if kind == "forecast":
        if region is None:
            raise HTTPException(422, "Forecast uploads need a region")
        if user.role != SM or user.region != region:
            raise forbidden("Only the region's Sales Manager uploads its forecast")
    elif user.role != PLANNER:
        raise forbidden("Only the Planner uploads inventory and allocation")
    comment = require_comment(comment, "An upload")
    content = file.file.read(MAX_UPLOAD + 1)
    if len(content) > MAX_UPLOAD:
        raise HTTPException(413, "File larger than 4 MB")

    # Uploading into a month that is not open yet opens it (stage 1), like months named in a Month column.
    selected = period.current()
    cycle = store.ensure_period_cycle(conn, selected) if selected else store.current_cycle(conn)
    result = clients.ingest_file(kind, file.filename or f"{kind}.xlsx", content, user.username)
    file_id = _record_file(result, kind, user, cycle["id"], comment)
    if result["status"] != "processed":
        raise invalid("File rejected", errors=result.get("errors", []))

    # New product names in a file are added to the product list (any kind of upload).
    ids = store.product_ids_by_name(conn)
    new_products = []
    groups: dict[str | None, list[tuple[int, dict]]] = {}
    for row in result.get("rows", []):
        name_key = row["product"].strip().lower()
        if name_key not in ids:
            ids[name_key] = store.ensure_product(conn, row["product"])
            new_products.append(row["product"].strip())
        groups.setdefault(row.get("month"), []).append((ids[name_key], row["values"]))

    # A Month column spreads one file over several month-years: each month is applied in its own
    # period (opened at stage 1 if new) and, for forecasts, becomes that month's next version.
    text = f"Excel upload {file.filename}: {comment}"
    outcomes = []
    for month, rows in sorted(groups.items(), key=lambda g: g[0] or ""):
        target = period.parse(month) if month else None
        with period.use(target if target else period.current()):
            if target:
                store.ensure_period_cycle(conn, target)
            label = period.label(store.current_cycle(conn)["period"])
            outcomes.append({"period": period.key(store.current_cycle(conn)["period"]), "label": label,
                             **_apply_upload(conn, user, kind, region, rows, text, file.filename)})

    applied = sum(o["applied"] for o in outcomes)
    message = "; ".join(f"{o['label']}: {o['message']}" for o in outcomes) if len(outcomes) > 1 else outcomes[0]["message"]
    if new_products:
        message += f". New products added: {', '.join(new_products[:10])}{' …' if len(new_products) > 10 else ''}"
    return {"fileId": file_id, "status": result["status"], "path": result.get("path"), "applied": applied,
            "revision": outcomes[0]["revision"] if len(outcomes) == 1 else None, "periods": outcomes,
            "newProducts": new_products, "message": message}


def _apply_upload(conn: Connection, user: User, kind: str, region: str | None, rows: list[tuple[int, dict]],
                  text: str, file_name: str | None) -> dict:
    """Apply one month's rows of an upload in the current period.

    Args:
        conn: database connection for this request.
        user: uploader.
        kind: forecast, inventory or allocation.
        region: forecast uploads only: the Sales Manager's region.
        rows: (product_id, row values) pairs for this month.
        text: comment recorded in the audit log.
        file_name: uploaded file name.

    Returns:
        {"applied": int, "revision": int | None, "message": str}.
    """
    revision, applied = None, 0
    if kind == "forecast":
        changes = {pid: v["qty"] for pid, v in rows}
        applied, revision = apply_forecast_changes(conn, user, region, 1, changes, text, source="upload", file_name=file_name)
        message = f"saved as version V{revision}" if revision else "no changes compared with the forecast"
    elif kind == "inventory":
        applied = apply_inventory_changes(conn, user, {pid: v["qty"] for pid, v in rows}, text, source_file=file_name,
                                          any_stage=True)
        message = f"inventory updated ({applied} products)"
    elif allocation_v1_open(conn, store.lock_cycle(conn)):
        changes = [(pid, r, v[r]) for pid, v in rows for r in REGIONS if r in v]
        applied = apply_allocation_changes(conn, user, changes, text, any_stage=True)
        message = f"allocation V1 updated ({applied} cells)"
    else:
        message = "validated and stored, but allocation V1 is already approved, so it was not applied"
    return {"applied": applied, "revision": revision, "message": message[0].upper() + message[1:]}


@router.get("/files")
def list_files(user: User = Depends(require_role(PLANNER, HEAD, ADMIN)), conn: Connection = Depends(get_db)):
    """Latest 200 Excel files received (uploads, SFTP inbound and exports) with their processing status.

    Args:
        user: signed-in caller (from the JWT); Planner, Head of Sales or Admin.
        conn: database connection for this request.

    Returns:
        list of {"id", "path", "kind", "status", "message", "uploadedBy", "receivedAt"}.
    """
    rows = conn.execute("SELECT * FROM file_ingest ORDER BY id DESC LIMIT 200").fetchall()
    return [
        {"id": r["id"], "path": r["path"], "kind": r["kind"], "status": r["status"], "message": r["message"],
         "uploadedBy": r["uploaded_by"], "receivedAt": r["received_at"].isoformat()}
        for r in rows
    ]


@router.get("/export/{kind}")
def export(kind: str, version: str | None = None, region: str | None = None, rev: int | None = None,
           month: str | None = None, user: User = Depends(require_role(*EVERYONE)), conn: Connection = Depends(get_db)):
    """Download an Excel export (forecast, inventory, allocation or audit), named with the month-year prefix.

    With `rev`, one region's forecast version is exported instead. files-svc also keeps a copy in SFTP /outbound.

    Args:
        kind: forecast, inventory, allocation or audit.
        version: forecast "1"/"2", or allocation "1"/"2"/"final".
        region: region of the forecast version to export (with `rev`).
        rev: forecast version number to export.
        month: audit only: None = the selected month, "all" = every month, or a month-year.
        user: signed-in caller (from the JWT).
        conn: database connection for this request.

    Returns:
        The .xlsx file as an attachment Response.

    Raises:
        HTTPException: 422 for an invalid version, month or region; 403 or 404 when the caller may not read
            that data; 404 for an unknown kind; 503 when files-svc is unavailable.
    """
    if kind == "forecast" and rev is not None:
        filename, sheet, cols, rows = exports.revision_table(conn, user, region, rev)
    else:
        filename, sheet, cols, rows = exports.table(conn, user, kind, version, month=month)
    if month == "all":
        prefix = "all-months"
    elif month:
        prefix = period.key(period.parse(month))
    else:
        prefix = period.key(store.current_cycle(conn)["period"])
    filename = f"{prefix}_{filename}"  # e.g. 2026-11_forecast_v1.xlsx, all-months_audit_trail.xlsx
    content = clients.export_file(filename, sheet, cols, rows)
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- rules ---------------------------------------------------------------------------------------

@router.get("/rules/catalogue")
def catalogue(user: User = Depends(current_user)):
    """List the business rules catalogue.

    Args:
        user: signed-in caller (from the JWT).

    Returns:
        list of {"id", "package", "description"}.
    """
    return clients.rules_catalogue()


@router.get("/config/rules")
def rule_config(user: User = Depends(current_user), conn: Connection = Depends(get_db)):
    """Return the current allocation rule settings.

    Args:
        user: signed-in caller (from the JWT).
        conn: database connection for this request.

    Returns:
        {"baselinePct": int, "sharing": "UNMET_DEMAND" | "PROPORTIONAL"}.
    """
    return store.get_rule_config(conn)


class RuleConfigBody(BaseModel):
    baselinePct: int = Field(ge=0, le=25)
    sharing: str = Field(pattern="^(UNMET_DEMAND|PROPORTIONAL)$")
    comment: str = ""


@router.put("/admin/rule-config")
def put_rule_config(body: RuleConfigBody, user: User = Depends(require_role(ADMIN)), conn: Connection = Depends(get_db)):
    """Admin changes the allocation rule settings (baseline % and sharing mode); the change is audited with before and after.

    Args:
        body: {"baselinePct": 0-25, "sharing": "UNMET_DEMAND" | "PROPORTIONAL", "comment": required reason}.
        user: signed-in caller (from the JWT); Admin.
        conn: database connection for this request.

    Returns:
        The updated settings {"baselinePct", "sharing"}.

    Raises:
        HTTPException: 422 when the comment is missing.
    """
    comment = require_comment(body.comment, "A rule configuration change")
    before = store.get_rule_config(conn)
    for key, value in (("baselinePct", body.baselinePct), ("sharing", body.sharing)):
        conn.execute(
            "INSERT INTO rule_config (key, value) VALUES (%s, to_jsonb(%s::text)) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
            if key == "sharing" else
            "INSERT INTO rule_config (key, value) VALUES (%s, to_jsonb(%s::int)) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            (key, value),
        )
    store.audit(conn, user, "workflow", cycle_id=store.current_cycle(conn)["id"], version="rule-config",
                comment=f"{before} → baselinePct={body.baselinePct}, sharing={body.sharing}: {comment}", status="override")
    return store.get_rule_config(conn)


# --- Admin ---------------------------------------------------------------------------------------

class StageBody(BaseModel):
    action: str = Field(pattern="^(advance|reset)$")
    comment: str = ""


@router.get("/admin/users")
def admin_users(user: User = Depends(require_role(ADMIN))):
    """Admin view of the Keycloak users with their PIFA role and region.

    Args:
        user: signed-in caller (from the JWT); Admin.

    Returns:
        list of {"username", "name", "email", "role", "region", "enabled"}.

    Raises:
        HTTPException: 503 when the Keycloak admin API is unavailable.
    """
    return clients.keycloak_users()


@router.post("/admin/stage")
def admin_stage(body: StageBody, user: User = Depends(require_role(ADMIN)), conn: Connection = Depends(get_db)):
    """Admin workflow override: "advance" completes the current stage for everyone, "reset" restarts the selected month at stage 1.

    Args:
        body: {"action": "advance" | "reset", "comment": required reason}.
        user: signed-in caller (from the JWT); Admin.
        conn: database connection for this request.

    Returns:
        The cycle view after the change (see workflow.cycle_view).

    Raises:
        HTTPException: 422 when the comment is missing; 409 when the cycle cannot be advanced (stage 5 or 6).
    """
    comment = require_comment(body.comment, "A workflow override")
    if body.action == "reset":
        workflow.admin_reset(conn, user, comment)
    else:
        workflow.admin_advance(conn, store.lock_cycle(conn), user, comment)
    return workflow.cycle_view(conn)


@router.get("/admin/health")
def admin_health(user: User = Depends(require_role(ADMIN))):
    """Admin health page: checks the database, Keycloak, the rules engine self-test, files-svc and its SFTP server.

    Args:
        user: signed-in caller (from the JWT); Admin.

    Returns:
        {component: {"ok": bool, "detail": str}} for api, database, keycloak, rules, files and sftp.
    """
    s = get_settings()
    out = {"api": {"ok": True, "detail": "FastAPI on Vercel"}}
    try:
        with db.connect() as c:
            c.execute("SELECT 1")
        out["database"] = {"ok": True, "detail": "SELECT 1 ok"}
    except Exception as e:  # noqa: BLE001 - report any failure
        out["database"] = {"ok": False, "detail": str(e)[:200]}
    ok, detail = clients.probe(f"{s.realm_base}/.well-known/openid-configuration")
    out["keycloak"] = {"ok": ok, "detail": detail}
    ok, detail = business_rules.self_test()
    out["rules"] = {"ok": ok, "detail": f"Python rules engine: {detail}"}
    try:
        r = httpx.get(f"{s.files_url}/health", timeout=8)
        body = r.json()
        out["files"] = {"ok": r.status_code < 400, "detail": f"HTTP {r.status_code}"}
        out["sftp"] = body.get("sftp", {"ok": False, "detail": "no SFTP status"})
    except (httpx.HTTPError, ValueError) as e:
        out["files"] = {"ok": False, "detail": str(e)[:200]}
        out["sftp"] = {"ok": False, "detail": "files-svc unreachable"}
    return out


# --- internal (files-svc poller) -----------------------------------------------------------------

class IngestReport(BaseModel):
    path: str
    kind: str
    status: str
    message: str = ""
    uploadedBy: str = "upstream"


@router.post("/internal/ingest")
def internal_ingest(body: IngestReport, caller: dict = Depends(service_caller), conn: Connection = Depends(get_db)):
    """Record a file the files-svc poller processed from SFTP (called with a service token, not a user token).

    Args:
        body: {"path", "kind", "status", "message", "uploadedBy"} reported by the poller.
        caller: verified service token claims.
        conn: database connection for this request.

    Returns:
        {"id": int}: the new file_ingest id.
    """
    row = conn.execute(
        "INSERT INTO file_ingest (path, kind, status, message, uploaded_by) VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (body.path, body.kind, body.status, body.message, body.uploadedBy),
    ).fetchone()
    store.audit(conn, None, "file", cycle_id=store.current_cycle(conn)["id"], version=body.kind,
                comment=f"{body.path}: {body.message}", status=body.status, username=body.uploadedBy, role="SYSTEM")
    return {"id": row["id"]}
