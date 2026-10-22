"""Forecast, inventory, allocation and transfer endpoints (Arch §9, FR-S/R/P/H)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg import Connection
from pydantic import BaseModel, Field

from . import clients, exports, store, workflow
from .auth import EVERYONE, READ_ALL, User, require_role
from .db import get_db
from .domain import HEAD, PLANNER, REGIONS, RM, SM, check_region, conflict, forbidden, require_comment

router = APIRouter(prefix="/api")


class QtyChange(BaseModel):
    productId: int
    qty: float  # validated as a whole number >= 0 by Drools R-FC-01


class ChangeSet(BaseModel):
    changes: list[QtyChange] = Field(min_length=1, max_length=2000)
    comment: str = ""


class RegionQtyChange(QtyChange):
    region: str


class AllocationChangeSet(BaseModel):
    changes: list[RegionQtyChange] = Field(min_length=1, max_length=8000)
    comment: str = ""


class CommentBody(BaseModel):
    comment: str = ""


class AutoBody(BaseModel):
    comment: str = ""
    basis: int = Field(2, ge=1, le=2)


class CellBody(BaseModel):
    qty: float
    comment: str = ""


class TransferBody(BaseModel):
    productId: int
    fromRegion: str
    toRegion: str
    qty: float
    comment: str = ""


def _str_keys(m: dict[int, int]) -> dict[str, int]:
    return {str(k): v for k, v in m.items()}


def _known_products(conn: Connection, ids) -> dict[int, str]:
    names = store.product_names(conn)
    unknown = sorted({i for i in ids if i not in names})
    if unknown:
        raise HTTPException(422, f"Unknown product id(s): {unknown}")
    return names


# --- forecast ------------------------------------------------------------------------------------

@router.get("/forecast")
def get_forecast(user: User = Depends(require_role(*EVERYONE)), conn: Connection = Depends(get_db)):
    cycle = store.current_cycle(conn)
    regions = [user.region] if user.role == SM else REGIONS
    out = {"regions": regions, "products": store.products(conn), "v1": {}, "v2": {}, "status": {}}
    for r in regions:
        v1 = store.forecast_version(conn, cycle["id"], r, 1)
        v2 = store.forecast_version(conn, cycle["id"], r, 2)
        # The Sales Manager sees their working copy; everyone else sees what was submitted.
        if v1 is None:
            out["v1"][r] = {}
        elif user.role == SM:
            out["v1"][r] = _str_keys(store.forecast_lines(conn, v1["id"]))
        else:
            out["v1"][r] = _str_keys(store.submitted_lines(conn, v1))
        out["v2"][r] = _str_keys(store.forecast_lines(conn, v2["id"])) if v2 else None
        out["status"][r] = {
            "v1": v1["status"] if v1 else None, "v2": v2["status"] if v2 else None,
            "v1Rev": v1["rev_no"] if v1 else None, "v2Rev": v2["rev_no"] if v2 else None,
            "v1SubmittedRev": v1["submitted_rev"] if v1 else None,
        }
    return out


def apply_forecast_changes(conn: Connection, user: User, region: str, version: int, changes: dict[int, float],
                           comment: str, source: str = "edit", file_name: str | None = None) -> tuple[int, int | None]:
    """Permission + stage checks, Drools R-FC-01/02, write lines, snapshot a new revision and audit each changed cell.

    Returns (changed lines, new revision number or None when nothing changed).
    """
    check_region(region)
    cycle = store.lock_cycle(conn)
    if version == 1:
        # The Sales Manager's working forecast is editable at every stage; each save is a new version.
        # While the region is in review (stage 1-2, submitted) the new version goes straight to the
        # Regional Manager (see _send_to_review). From Planning on, edits stay in the working copy.
        if user.role != SM or user.region != region:
            raise forbidden("Only the region's Sales Manager edits their forecast")
        fv = store.ensure_forecast_version(conn, cycle["id"], region, 1)
    elif version == 2:
        # The Regional Manager edits their region throughout stage 2, also after approving it;
        # an edit to an approved forecast returns it to draft so it is approved again.
        if user.role != RM or user.region != region:
            raise forbidden("Only the region's Regional Manager edits forecast V2")
        workflow.require_stage(cycle, 2)
        fv = store.forecast_version(conn, cycle["id"], region, 2)
        if fv is None or fv["status"] not in ("draft", "approved"):
            raise conflict(f"The {region} forecast is not submitted by its Sales Manager yet")
    else:
        raise HTTPException(422, "version must be 1 or 2")
    comment = require_comment(comment)
    names = _known_products(conn, changes)
    clients.enforce("forecast", {"changes": [
        {"entity": "forecast", "product": names[pid], "region": region, "qty": qty, "comment": comment,
         "isRevision": version == 2}
        for pid, qty in changes.items()
    ]}, "Forecast change violates business rules")

    before = store.forecast_lines(conn, fv["id"])
    changed = {pid: int(qty) for pid, qty in changes.items() if before.get(pid, 0) != int(qty)}
    if not changed:
        return 0, None
    store.write_forecast_lines(conn, fv["id"], changed)
    rev_no = store.create_revision(conn, cycle["id"], region, fv, user, source=source, comment=comment,
                                   changed=len(changed), file_name=file_name)
    for pid, qty in changed.items():
        store.audit(conn, user, "forecast", cycle_id=cycle["id"], region=region, version=f"V{rev_no}", product_id=pid,
                    before=before.get(pid, 0), after=qty, comment=comment, status=fv["status"])
    if version == 1:
        _send_to_review(conn, cycle, region, fv, rev_no, user)
    elif fv["status"] == "approved":
        store.set_forecast_status(conn, fv["id"], "draft", user.username)
        store.audit(conn, user, "forecast", cycle_id=cycle["id"], region=region, version=f"V{rev_no}",
                    comment="Edited after approval; approve again", status="draft")
    return len(changed), rev_no


def _send_to_review(conn: Connection, cycle: dict, region: str, v1: dict, rev_no: int, user: User) -> None:
    """A Sales Manager save on a submitted forecast during review becomes the version under review.

    The Regional Manager's revision restarts from it (their earlier revision stays in the history and can be
    restored) and any approval is withdrawn, so the region is approved again on the new numbers.
    """
    if v1["status"] != "submitted" or cycle["stage"] > 2:
        return
    v2 = store.forecast_version(conn, cycle["id"], region, 2)
    store.set_submitted_rev(conn, v1["id"], rev_no)
    if v2 is not None:
        store.copy_forecast(conn, v1["id"], v2["id"])
        store.set_version_rev(conn, v2["id"], rev_no)
        store.set_forecast_status(conn, v2["id"], "draft", user.username)
    store.audit(conn, user, "forecast", cycle_id=cycle["id"], region=region, version=f"V{rev_no}",
                comment=f"Sales Manager updated the submitted forecast to V{rev_no}; regional review restarts from it",
                status="submitted")


@router.put("/forecast/{region}")
def put_forecast(region: str, body: ChangeSet, version: int = Query(..., ge=1, le=2),
                 user: User = Depends(require_role(SM, RM)), conn: Connection = Depends(get_db)):
    changes = {c.productId: c.qty for c in body.changes}
    updated, rev_no = apply_forecast_changes(conn, user, region, version, changes, body.comment)
    return {"updated": updated, "revision": rev_no}


@router.get("/forecast/{region}/revisions")
def list_revisions(region: str, user: User = Depends(require_role(*EVERYONE)), conn: Connection = Depends(get_db)):
    check_region(region)
    if not user.can_read_region(region):
        raise forbidden("You can only see your own region")
    return store.revisions(conn, store.current_cycle(conn)["id"], region)


@router.get("/forecast/{region}/revisions/{rev_no}")
def get_revision(region: str, rev_no: int, user: User = Depends(require_role(*EVERYONE)), conn: Connection = Depends(get_db)):
    check_region(region)
    if not user.can_read_region(region):
        raise forbidden("You can only see your own region")
    cycle_id = store.current_cycle(conn)["id"]
    lines = store.revision_lines(conn, cycle_id, region, rev_no)
    if lines is None:
        raise HTTPException(404, f"{region} has no version V{rev_no}")
    meta = next(r for r in store.revisions(conn, cycle_id, region) if r["revNo"] == rev_no)
    return meta | {"lines": _str_keys(lines)}


@router.post("/forecast/{region}/revisions/{rev_no}/restore")
def restore_revision(region: str, rev_no: int, body: CommentBody, user: User = Depends(require_role(SM, RM)),
                     conn: Connection = Depends(get_db)):
    """Copy an older version's quantities into the caller's working stage; the result is a new version."""
    check_region(region)
    lines = store.revision_lines(conn, store.current_cycle(conn)["id"], region, rev_no)
    if lines is None:
        raise HTTPException(404, f"{region} has no version V{rev_no}")
    comment = require_comment(body.comment, "A restore")
    changes = {pid: lines.get(pid, 0) for pid in store.product_names(conn)}
    updated, new_rev = apply_forecast_changes(conn, user, region, 1 if user.role == SM else 2, changes,
                                              f"Restored V{rev_no}: {comment}", source="restore")
    if new_rev is None:
        raise conflict(f"The working forecast already matches V{rev_no}")
    return {"updated": updated, "revision": new_rev}


@router.post("/forecast/{region}/submit")
def submit_forecast(region: str, body: CommentBody, user: User = Depends(require_role(SM)),
                    conn: Connection = Depends(get_db)):
    check_region(region)
    if user.region != region:
        raise forbidden("You can only submit your own region")
    cycle = store.lock_cycle(conn)
    workflow.require_stage(cycle, 1, 2)
    fv = store.ensure_forecast_version(conn, cycle["id"], region, 1)
    if fv["status"] not in ("draft", "rejected"):
        raise conflict(f"Forecast V1 for {region} is already {fv['status']}")
    workflow.submit_forecast(conn, cycle, region, user, body.comment.strip() or "Submitted forecast V1")
    return workflow.cycle_view(conn)


def _review(region: str, user: User, conn: Connection, decision: str, comment: str) -> dict:
    check_region(region)
    if user.region != region:
        raise forbidden("You can only review your own region")
    cycle = store.lock_cycle(conn)
    workflow.require_stage(cycle, 2)
    v2 = store.forecast_version(conn, cycle["id"], region, 2)
    if v2 is None or v2["status"] != "draft":
        raise conflict(f"Forecast for {region} is not awaiting review")
    clients.enforce("forecast", {"changes": [], "review": {"actorRole": user.role, "decision": decision, "comment": comment}},
                    "Review violates business rules")
    if decision == "APPROVE":
        workflow.approve_forecast(conn, cycle, region, user, comment.strip() or "Approved forecast V2")
    else:
        workflow.reject_forecast(conn, cycle, region, user, require_comment(comment, "A rejection"))
    return workflow.cycle_view(conn)


@router.post("/forecast/{region}/approve")
def approve_forecast(region: str, body: CommentBody, user: User = Depends(require_role(RM)),
                     conn: Connection = Depends(get_db)):
    return _review(region, user, conn, "APPROVE", body.comment)


@router.post("/forecast/{region}/reject")
def reject_forecast(region: str, body: CommentBody, user: User = Depends(require_role(RM)),
                    conn: Connection = Depends(get_db)):
    require_comment(body.comment, "A rejection")
    return _review(region, user, conn, "REJECT", body.comment)


# --- inventory -----------------------------------------------------------------------------------

@router.get("/inventory")
def get_inventory(user: User = Depends(require_role(*READ_ALL)), conn: Connection = Depends(get_db)):
    cycle = store.current_cycle(conn)
    snap = store.inventory_snapshot(conn, cycle["id"])
    return {
        "snapshot": {
            "id": snap["id"], "sourceFile": snap["source_file"], "uploadedBy": snap["uploaded_by"],
            "createdAt": snap["created_at"].isoformat(),
        } if snap else None,
        "lines": _str_keys(store.inventory_lines(conn, snap["id"] if snap else None)),
    }


def apply_inventory_changes(conn: Connection, user: User, changes: dict[int, float], comment: str,
                            source_file: str | None = None, any_stage: bool = False) -> int:
    """Cell edits are a stage-3 action; Excel uploads (any_stage) are accepted at every stage.

    Late inventory changes stay safe: allocation submit and final approval re-check R-ALLOC-02.
    """
    cycle = store.lock_cycle(conn)
    if not any_stage:
        workflow.require_stage(cycle, 3)
    comment = require_comment(comment)
    names = _known_products(conn, changes)
    clients.enforce("forecast", {"changes": [
        {"entity": "inventory", "product": names[pid], "region": None, "qty": qty, "comment": comment, "isRevision": False}
        for pid, qty in changes.items()
    ]}, "Inventory change violates business rules")
    snap = store.inventory_snapshot(conn, cycle["id"])
    if snap is None or source_file:
        snap = store.new_inventory_snapshot(conn, cycle["id"], user.username, source_file)
    before = store.inventory_lines(conn, snap["id"])
    changed = {pid: int(q) for pid, q in changes.items() if before.get(pid) != int(q)}
    store.write_inventory_lines(conn, snap["id"], changed)
    for pid, qty in changed.items():
        store.audit(conn, user, "inventory", cycle_id=cycle["id"], region=None, version=f"S{snap['id']}", product_id=pid,
                    before=before.get(pid, 0), after=qty, comment=comment, status="draft")
    return len(changed)


@router.put("/inventory")
def put_inventory(body: ChangeSet, user: User = Depends(require_role(PLANNER)), conn: Connection = Depends(get_db)):
    return {"updated": apply_inventory_changes(conn, user, {c.productId: c.qty for c in body.changes}, body.comment)}


# --- allocation ----------------------------------------------------------------------------------

def _alloc_json(alloc: store.AllocMap, regions: list[str]) -> dict:
    return {r: _str_keys(alloc[r]) for r in regions}


@router.get("/allocation")
def get_allocation(user: User = Depends(require_role(*EVERYONE)), conn: Connection = Depends(get_db)):
    cycle = store.current_cycle(conn)
    regions = [user.region] if user.role == SM else REGIONS
    out = {"regions": regions, "status": {}}
    for key, vno in (("v1", "1"), ("v2", "2"), ("final", "final")):
        av = store.allocation_version(conn, cycle["id"], vno)
        out[key] = _alloc_json(store.allocation_lines(conn, av["id"]), regions) if av else None
        out["status"][key] = av["status"] if av else None
    return out


def allocation_v1_open(conn: Connection, cycle: dict) -> bool:
    """Allocation V1 can still change: before the Planner approves it (stages 1-3)."""
    v1 = store.allocation_version(conn, cycle["id"], "1")
    return cycle["stage"] <= 3 and (v1 is None or v1["status"] == "draft")


def apply_allocation_changes(conn: Connection, user: User, changes: list[tuple[int, str, float]], comment: str,
                             any_stage: bool = False) -> int:
    """Cell edits and auto-allocate are stage-3 actions; uploads (any_stage) may prepare V1 earlier, until it is approved."""
    cycle = store.lock_cycle(conn)
    if not any_stage:
        workflow.require_stage(cycle, 3)
    elif not allocation_v1_open(conn, cycle):
        raise conflict("Allocation V1 is already approved")
    comment = require_comment(comment)
    for _, region, _ in changes:
        check_region(region)
    names = _known_products(conn, [pid for pid, _, _ in changes])
    clients.enforce("forecast", {"changes": [
        {"entity": "allocation", "product": names[pid], "region": region, "qty": qty, "comment": comment, "isRevision": False}
        for pid, region, qty in changes
    ]}, "Allocation change violates business rules")
    v1 = store.ensure_allocation_version(conn, cycle["id"], "1")
    before = store.allocation_lines(conn, v1["id"])
    n = 0
    for pid, region, qty in changes:
        old = before[region].get(pid, 0)
        if old == int(qty):
            continue
        store.write_allocation_line(conn, v1["id"], pid, region, int(qty))
        store.audit(conn, user, "allocation", cycle_id=cycle["id"], region=region, version="V1", product_id=pid,
                    before=old, after=int(qty), comment=comment, status="draft")
        n += 1
    return n


@router.post("/allocation/auto")
def auto_allocate(body: AutoBody, user: User = Depends(require_role(PLANNER)), conn: Connection = Depends(get_db)):
    cycle = store.lock_cycle(conn)
    workflow.require_stage(cycle, 3)
    comment = require_comment(body.comment, "Auto-allocation")
    if store.inventory_snapshot(conn, cycle["id"]) is None:
        raise conflict("Upload or enter inventory before auto-allocating")
    empty = {r: {} for r in REGIONS}
    result = clients.rules("allocation", {
        "mode": "ALLOCATE", "config": store.get_rule_config(conn),
        "models": workflow.allocation_models(conn, cycle["id"], empty, demand_version=body.basis),
    })
    ids = store.product_ids_by_name(conn)
    changes = [(ids[a["product"].strip().lower()], a["region"], a["qty"]) for a in result.get("allocations", [])]
    apply_allocation_changes(conn, user, changes, f"Auto-allocate (R-ALLOC-01, forecast V{body.basis}): {comment}")
    v1 = store.allocation_version(conn, cycle["id"], "1")
    return {"v1": _alloc_json(store.allocation_lines(conn, v1["id"]), REGIONS), "violations": result.get("violations", [])}


@router.put("/allocation/v1")
def put_allocation(body: AllocationChangeSet, user: User = Depends(require_role(PLANNER)),
                   conn: Connection = Depends(get_db)):
    changes = [(c.productId, c.region, c.qty) for c in body.changes]
    return {"updated": apply_allocation_changes(conn, user, changes, body.comment)}


@router.put("/allocation/v1/{region}/{product_id}")
def put_allocation_cell(region: str, product_id: int, body: CellBody, user: User = Depends(require_role(PLANNER)),
                        conn: Connection = Depends(get_db)):
    return {"updated": apply_allocation_changes(conn, user, [(product_id, region, body.qty)], body.comment)}


@router.post("/allocation/submit")
def submit_allocation(body: CommentBody, user: User = Depends(require_role(PLANNER)), conn: Connection = Depends(get_db)):
    cycle = store.lock_cycle(conn)
    workflow.require_stage(cycle, 3)
    workflow.submit_allocation(conn, cycle, user, body.comment.strip() or "Approved allocation V1")
    return workflow.cycle_view(conn)


@router.post("/allocation/confirm")
def confirm_allocation(body: CommentBody, user: User = Depends(require_role(RM)), conn: Connection = Depends(get_db)):
    cycle = store.lock_cycle(conn)
    workflow.require_stage(cycle, 4)
    workflow.confirm_region(conn, cycle, user.region, user, body.comment.strip() or "Confirmed allocation review")
    return workflow.cycle_view(conn)


def _final_decision(decision: str, body: CommentBody, user: User, conn: Connection) -> dict:
    cycle = store.lock_cycle(conn)
    clients.enforce("approval", {"request": {"actorRole": user.role, "decision": decision, "comment": body.comment,
                                             "stage": cycle["stage"]}}, "Approval violates business rules")
    workflow.require_stage(cycle, 5)
    if decision == "APPROVE":
        workflow.publish(conn, cycle, user, body.comment.strip() or "Approved final allocation")
    else:
        workflow.reject_final(conn, cycle, user, require_comment(body.comment, "A rejection"))
    return workflow.cycle_view(conn)


@router.post("/allocation/approve")
def approve_allocation(body: CommentBody, user: User = Depends(require_role(HEAD)), conn: Connection = Depends(get_db)):
    view = _final_decision("APPROVE", body, user, conn)
    conn.commit()  # publish is durable even if the outbound export below fails
    exports.write_published_export(conn, user)
    return view


@router.post("/allocation/reject")
def reject_allocation(body: CommentBody, user: User = Depends(require_role(HEAD)), conn: Connection = Depends(get_db)):
    require_comment(body.comment, "A rejection")
    return _final_decision("REJECT", body, user, conn)


# --- transfers -----------------------------------------------------------------------------------

def _transfer_json(t: dict) -> dict:
    return {
        "id": t["id"], "productId": t["product_id"], "product": t["product"], "fromRegion": t["from_region"],
        "toRegion": t["to_region"], "qty": t["qty"], "comment": t["comment"], "requestedBy": t["requested_by"],
        "requestedRegion": t["requested_region"], "status": t["status"], "createdAt": t["created_at"].isoformat(),
        "decidedBy": t.get("decided_by"), "decidedAt": t["decided_at"].isoformat() if t.get("decided_at") else None,
        "decisionComment": t.get("decision_comment"),
    }


@router.get("/transfers")
def list_transfers(user: User = Depends(require_role(*READ_ALL)), conn: Connection = Depends(get_db)):
    return [_transfer_json(t) for t in store.transfers(conn, store.current_cycle(conn)["id"])]


def _move(conn: Connection, v2_id: int, pid: int, src: str, dst: str, qty: int) -> tuple[int, int, int, int]:
    alloc = store.allocation_lines(conn, v2_id)
    s0, d0 = alloc[src].get(pid, 0), alloc[dst].get(pid, 0)
    store.write_allocation_line(conn, v2_id, pid, src, s0 - qty)
    store.write_allocation_line(conn, v2_id, pid, dst, d0 + qty)
    return s0, s0 - qty, d0, d0 + qty


@router.post("/transfers")
def create_transfer(body: TransferBody, user: User = Depends(require_role(RM)), conn: Connection = Depends(get_db)):
    check_region(body.fromRegion)
    check_region(body.toRegion)
    cycle = store.lock_cycle(conn)
    workflow.require_stage(cycle, 4)
    names = _known_products(conn, [body.productId])
    v2 = store.allocation_version(conn, cycle["id"], "2")
    source_qty = store.allocation_lines(conn, v2["id"])[body.fromRegion].get(body.productId, 0)
    clients.enforce("transfer", {"transfer": {
        "product": names[body.productId], "fromRegion": body.fromRegion, "toRegion": body.toRegion,
        "qty": body.qty, "sourceQty": source_qty, "comment": body.comment,
    }}, "Transfer violates business rules")
    qty = int(body.qty)
    comment = require_comment(body.comment)
    t = conn.execute(
        """INSERT INTO transfer_request (cycle_id, product_id, from_region, to_region, qty, comment, requested_by, requested_region)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (cycle["id"], body.productId, body.fromRegion, body.toRegion, qty, comment, user.username, user.region),
    ).fetchone()
    s0, s1, d0, d1 = _move(conn, v2["id"], body.productId, body.fromRegion, body.toRegion, qty)
    store.clear_confirmations(conn, cycle["id"])
    for region, b, a in ((body.fromRegion, s0, s1), (body.toRegion, d0, d1)):
        store.audit(conn, user, "transfer", cycle_id=cycle["id"], region=region, version="V2", product_id=body.productId,
                    before=b, after=a, comment=f"T{t['id']} {body.fromRegion}→{body.toRegion}: {comment}", status="pending")
    return _transfer_json(store.transfer_row(conn, t["id"]))


@router.post("/transfers/{transfer_id}/undo")
def undo_transfer(transfer_id: int, body: CommentBody, user: User = Depends(require_role(RM)),
                  conn: Connection = Depends(get_db)):
    cycle = store.lock_cycle(conn)
    workflow.require_stage(cycle, 4)
    t = store.transfer_row(conn, transfer_id)
    if t is None or t["cycle_id"] != cycle["id"]:
        raise HTTPException(404, "Transfer not found")
    if t["requested_by"] != user.username:
        raise forbidden("You can only undo your own transfers")
    if t["status"] != "pending":
        raise conflict(f"Transfer is {t['status']}")
    comment = require_comment(body.comment, "Undo")
    v2 = store.allocation_version(conn, cycle["id"], "2")
    available = store.allocation_lines(conn, v2["id"])[t["to_region"]].get(t["product_id"], 0)
    if available < t["qty"]:
        raise conflict(f"{t['to_region']} now holds only {available} units; undo would go negative")
    s0, s1, d0, d1 = _move(conn, v2["id"], t["product_id"], t["to_region"], t["from_region"], t["qty"])
    conn.execute("UPDATE transfer_request SET status = 'undone' WHERE id = %s", (transfer_id,))
    store.clear_confirmations(conn, cycle["id"])
    for region, b, a in ((t["to_region"], s0, s1), (t["from_region"], d0, d1)):
        store.audit(conn, user, "transfer", cycle_id=cycle["id"], region=region, version="V2", product_id=t["product_id"],
                    before=b, after=a, comment=f"Undo T{transfer_id}: {comment}", status="undone")
    return _transfer_json(store.transfer_row(conn, transfer_id))


# --- Head of Sales decisions on transfers (stage 5) -------------------------------------------------

def _head_decision_guard(conn: Connection, user: User, decision: str, comment: str) -> dict:
    cycle = store.lock_cycle(conn)
    clients.enforce("approval", {"request": {"actorRole": user.role, "decision": decision, "comment": comment,
                                             "stage": cycle["stage"]}}, "Decision violates business rules")
    workflow.require_stage(cycle, 5)
    return cycle


def _decide(conn: Connection, user: User, cycle: dict, t: dict, status: str, comment: str) -> None:
    conn.execute(
        """UPDATE transfer_request SET status = %s, decided_by = %s, decided_at = now(), decision_comment = %s
           WHERE id = %s""",
        (status, user.username, comment or None, t["id"]),
    )
    store.audit(conn, user, "transfer", cycle_id=cycle["id"], region=t["to_region"], version="V2", product_id=t["product_id"],
                comment=f"T{t['id']} {t['from_region']}→{t['to_region']} {t['qty']} units {status}" + (f": {comment}" if comment else ""),
                status=status)


def _pending_transfer(conn: Connection, cycle: dict, transfer_id: int) -> dict:
    t = store.transfer_row(conn, transfer_id)
    if t is None or t["cycle_id"] != cycle["id"]:
        raise HTTPException(404, "Transfer not found")
    if t["status"] != "pending":
        raise conflict(f"Transfer is already {t['status']}")
    return t


@router.post("/transfers/{transfer_id}/approve")
def approve_transfer(transfer_id: int, body: CommentBody, user: User = Depends(require_role(HEAD)),
                     conn: Connection = Depends(get_db)):
    cycle = _head_decision_guard(conn, user, "APPROVE", body.comment)
    t = _pending_transfer(conn, cycle, transfer_id)
    _decide(conn, user, cycle, t, "approved", body.comment.strip())
    return _transfer_json(store.transfer_row(conn, transfer_id))


@router.post("/transfers/{transfer_id}/reject")
def reject_transfer(transfer_id: int, body: CommentBody, user: User = Depends(require_role(HEAD)),
                    conn: Connection = Depends(get_db)):
    """Reject one transfer: its units move back in allocation V2 (the other decisions stand)."""
    comment = require_comment(body.comment, "A rejection")
    cycle = _head_decision_guard(conn, user, "REJECT", comment)
    t = _pending_transfer(conn, cycle, transfer_id)
    v2 = store.allocation_version(conn, cycle["id"], "2")
    available = store.allocation_lines(conn, v2["id"])[t["to_region"]].get(t["product_id"], 0)
    if available < t["qty"]:
        raise conflict(f"{t['to_region']} now holds only {available} units of {t['product']}; this transfer cannot be reversed")
    s0, s1, d0, d1 = _move(conn, v2["id"], t["product_id"], t["to_region"], t["from_region"], t["qty"])
    for region, b, a in ((t["to_region"], s0, s1), (t["from_region"], d0, d1)):
        store.audit(conn, user, "transfer", cycle_id=cycle["id"], region=region, version="V2", product_id=t["product_id"],
                    before=b, after=a, comment=f"Reversed rejected T{transfer_id}: {comment}", status="rejected")
    _decide(conn, user, cycle, t, "rejected", comment)
    return _transfer_json(store.transfer_row(conn, transfer_id))


@router.post("/transfers/approve-all")
def approve_all_transfers(body: CommentBody, user: User = Depends(require_role(HEAD)), conn: Connection = Depends(get_db)):
    cycle = _head_decision_guard(conn, user, "APPROVE", body.comment)
    pending = [t for t in store.transfers(conn, cycle["id"]) if t["status"] == "pending"]
    for t in pending:
        _decide(conn, user, cycle, t, "approved", body.comment.strip() or "Approved with all pending transfers")
    return {"approved": len(pending)}
