"""Identity, cycle, summary, audit, Excel files, exports, Admin and internal endpoints."""

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from psycopg import Connection
from pydantic import BaseModel, Field

from . import clients, db, exports, store, workflow
from .auth import EVERYONE, READ_ALL, User, current_user, require_role, service_caller
from .config import get_settings
from .db import get_db
from .domain import ADMIN, HEAD, PLANNER, REGIONS, SM, forbidden, invalid, require_comment
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
    return {"username": user.username, "name": user.name, "role": user.role, "region": user.region, "claims": user.claims}


@router.get("/cycle")
def get_cycle(user: User = Depends(current_user), conn: Connection = Depends(get_db)):
    return workflow.cycle_view(conn)


@router.get("/products")
def get_products(user: User = Depends(current_user), conn: Connection = Depends(get_db)):
    return store.products(conn)


@router.get("/summary")
def summary(user: User = Depends(require_role(*READ_ALL)), conn: Connection = Depends(get_db)):
    cid = store.current_cycle(conn)["id"]
    f1, f2 = store.forecast_totals(conn, cid, 1), store.forecast_totals(conn, cid, 2)
    snap = store.inventory_snapshot(conn, cid)
    allocs = {}
    for key in ("1", "2", "final"):
        av = store.allocation_version(conn, cid, key)
        allocs[key] = store.allocation_lines(conn, av["id"]) if av else None

    def total(m: dict | None, region: str) -> int | None:
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
          limit: int = Query(500, ge=1, le=5000), user: User = Depends(require_role(*EVERYONE)),
          conn: Connection = Depends(get_db)):
    return store.audit_entries(conn, user, role=role, entity=entity, region=region, q=q, limit=limit)


# --- Excel files ---------------------------------------------------------------------------------

def _record_file(result: dict, kind: str, user: User, cycle_id: int, comment: str) -> int:
    """Committed on its own connection so rejected uploads stay on record."""
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

    cycle = store.current_cycle(conn)
    result = clients.ingest_file(kind, file.filename or f"{kind}.xlsx", content, user.username)
    file_id = _record_file(result, kind, user, cycle["id"], comment)
    if result["status"] != "processed":
        raise invalid("File rejected", errors=result.get("errors", []))

    ids = store.product_ids_by_name(conn)
    errors = []
    changes: dict = {}
    alloc_changes: list = []
    for row in result.get("rows", []):
        pid = ids.get(row["product"].strip().lower())
        if pid is None and kind == "inventory":
            pid = ids[row["product"].strip().lower()] = store.ensure_product(conn, row["product"])
        if pid is None:
            errors.append({"row": row["row"], "message": f"Unknown product '{row['product']}'"})
            continue
        if kind == "allocation":
            alloc_changes += [(pid, r, row["values"][r]) for r in REGIONS if r in row["values"]]
        else:
            changes[pid] = row["values"]["qty"]
    if errors:
        raise invalid("File has unknown products", errors=errors)

    text = f"Excel upload {file.filename}: {comment}"
    revision, applied, message = None, 0, None
    if kind == "forecast":
        applied, revision = (apply_forecast_changes(conn, user, region, 1, changes, text, source="upload",
                                                    file_name=file.filename) if changes else (0, None))
        message = f"Saved as version V{revision}" if revision else "No changes compared with your forecast"
    elif kind == "inventory":
        applied = apply_inventory_changes(conn, user, changes, text, source_file=file.filename, any_stage=True) if changes else 0
        message = f"Inventory updated ({applied} products)"
    elif allocation_v1_open(conn, store.lock_cycle(conn)):
        applied = apply_allocation_changes(conn, user, alloc_changes, text, any_stage=True) if alloc_changes else 0
        message = f"Allocation V1 updated ({applied} cells)"
    else:
        message = "File validated and stored, but allocation V1 is already approved, so it was not applied."
    return {"fileId": file_id, "status": result["status"], "path": result.get("path"), "applied": applied,
            "revision": revision, "message": message}


@router.get("/files")
def list_files(user: User = Depends(require_role(PLANNER, HEAD, ADMIN)), conn: Connection = Depends(get_db)):
    rows = conn.execute("SELECT * FROM file_ingest ORDER BY id DESC LIMIT 200").fetchall()
    return [
        {"id": r["id"], "path": r["path"], "kind": r["kind"], "status": r["status"], "message": r["message"],
         "uploadedBy": r["uploaded_by"], "receivedAt": r["received_at"].isoformat()}
        for r in rows
    ]


@router.get("/export/{kind}")
def export(kind: str, version: str | None = None, region: str | None = None, rev: int | None = None,
           user: User = Depends(require_role(*EVERYONE)), conn: Connection = Depends(get_db)):
    if kind == "forecast" and rev is not None:
        filename, sheet, cols, rows = exports.revision_table(conn, user, region, rev)
    else:
        filename, sheet, cols, rows = exports.table(conn, user, kind, version)
    content = clients.export_file(filename, sheet, cols, rows)
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- rules ---------------------------------------------------------------------------------------

@router.get("/rules/catalogue")
def catalogue(user: User = Depends(current_user)):
    return clients.rules_catalogue()


@router.get("/config/rules")
def rule_config(user: User = Depends(current_user), conn: Connection = Depends(get_db)):
    return store.get_rule_config(conn)


class RuleConfigBody(BaseModel):
    baselinePct: int = Field(ge=0, le=25)
    sharing: str = Field(pattern="^(UNMET_DEMAND|PROPORTIONAL)$")
    comment: str = ""


@router.put("/admin/rule-config")
def put_rule_config(body: RuleConfigBody, user: User = Depends(require_role(ADMIN)), conn: Connection = Depends(get_db)):
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
    return clients.keycloak_users()


@router.post("/admin/stage")
def admin_stage(body: StageBody, user: User = Depends(require_role(ADMIN)), conn: Connection = Depends(get_db)):
    comment = require_comment(body.comment, "A workflow override")
    if body.action == "reset":
        workflow.admin_reset(conn, user, comment)
    else:
        workflow.admin_advance(conn, store.lock_cycle(conn), user, comment)
    return workflow.cycle_view(conn)


@router.get("/admin/health")
def admin_health(user: User = Depends(require_role(ADMIN))):
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
    ok, detail = clients.probe(f"{s.rules_url}/health")
    out["rules"] = {"ok": ok, "detail": detail}
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
    row = conn.execute(
        "INSERT INTO file_ingest (path, kind, status, message, uploaded_by) VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (body.path, body.kind, body.status, body.message, body.uploadedBy),
    ).fetchone()
    store.audit(conn, None, "file", cycle_id=store.current_cycle(conn)["id"], version=body.kind,
                comment=f"{body.path}: {body.message}", status=body.status, username=body.uploadedBy, role="SYSTEM")
    return {"id": row["id"]}
