"""Cycle state machine (Arch §5): stage transitions shared by user actions and Admin overrides."""

from psycopg import Connection

from . import clients, period, store
from .auth import User
from .domain import REGIONS, STAGES, conflict


def cycle_view(conn: Connection) -> dict:
    """Snapshot of the selected month's planning cycle for the dashboard.

    Shows the stage, forecast and allocation statuses per region, the regional confirmations and who must act next.

    Args:
        conn: database connection for this request.

    Returns:
        {"id", "name", "period", "periodLabel", "stage", "stageKey", "forecast": {region: {"v1", "v2"}},
        "allocation": {"v1", "v2", "final"}, "confirmations": {region: {"by", "at"} | None}, "nextActor": str}.
    """
    cycle = store.current_cycle(conn)
    cid = cycle["id"]
    fv = conn.execute("SELECT region, version_no, status FROM forecast_version WHERE cycle_id = %s", (cid,)).fetchall()
    forecast = {r: {"v1": None, "v2": None} for r in REGIONS}
    for row in fv:
        forecast[row["region"]][f"v{row['version_no']}"] = row["status"]
    av = conn.execute("SELECT version_no, status FROM allocation_version WHERE cycle_id = %s", (cid,)).fetchall()
    allocation = {"v1": None, "v2": None, "final": None}
    for row in av:
        allocation["final" if row["version_no"] == "final" else f"v{row['version_no']}"] = row["status"]
    conf = store.confirmations(conn, cid)
    confirmations = {
        r: ({"by": conf[r]["confirmed_by"], "at": conf[r]["confirmed_at"].isoformat()} if r in conf else None)
        for r in REGIONS
    }
    return {
        "id": cid,
        "name": cycle["name"],
        "period": period.key(cycle["period"]),
        "periodLabel": period.label(cycle["period"]),
        "stage": cycle["stage"],
        "stageKey": STAGES[cycle["stage"]],
        "forecast": forecast,
        "allocation": allocation,
        "confirmations": confirmations,
        "nextActor": _next_actor(cycle["stage"], forecast, confirmations),
    }


def _next_actor(stage: int, forecast: dict, confirmations: dict) -> str:
    """Describe who has to act next at the given stage (e.g. which regions' Sales Managers still need to submit).

    Args:
        stage: current stage number (1-6).
        forecast: per-region {"v1", "v2"} forecast statuses from cycle_view.
        confirmations: per-region confirmation, or None when the region has not confirmed.

    Returns:
        Human-readable text such as "Sales Managers: North, West".
    """
    if stage == 1:
        waiting = [r for r in REGIONS if forecast[r]["v1"] != "submitted"]
        return f"Sales Managers: {', '.join(waiting)}" if waiting else "Regional Managers"
    if stage == 2:
        resubmit = [r for r in REGIONS if forecast[r]["v1"] == "rejected"]
        review = [r for r in REGIONS if forecast[r]["v1"] == "submitted" and forecast[r]["v2"] != "approved"]
        parts = []
        if review:
            parts.append(f"Regional Managers: {', '.join(review)}")
        if resubmit:
            parts.append(f"Sales Managers (resubmit): {', '.join(resubmit)}")
        return "; ".join(parts) or "Planner"
    if stage == 3:
        return "Planner"
    if stage == 4:
        waiting = [r for r in REGIONS if confirmations[r] is None]
        return f"Regional Managers: {', '.join(waiting)}" if waiting else "Head of Sales"
    if stage == 5:
        return "Head of Sales"
    return "Published: no further action"


def require_stage(cycle: dict, *stages: int) -> None:
    """Guard that an action is allowed in the cycle's current stage.

    Args:
        cycle: cycle row.
        *stages: stage numbers in which the action is allowed.

    Returns:
        None

    Raises:
        HTTPException: 409 when the cycle is in another stage.
    """
    if cycle["stage"] not in stages:
        allowed = " or ".join(STAGES[s] for s in stages)
        raise conflict(f"Not allowed at stage {STAGES[cycle['stage']]}; requires {allowed}")


def _advance(conn: Connection, cycle: dict, to_stage: int, user: User | None, comment: str) -> None:
    """Move the cycle to a new stage and audit the transition.

    Args:
        conn: database connection for this request.
        cycle: cycle row; its "stage" is updated in place.
        to_stage: new stage number.
        user: acting user, or None for the system.
        comment: reason recorded in the audit log.

    Returns:
        None
    """
    store.set_stage(conn, cycle["id"], to_stage)
    cycle["stage"] = to_stage
    store.audit(conn, user, "workflow", cycle_id=cycle["id"], region=None, version=STAGES[to_stage],
                comment=comment, status="stage")


# --- forecast (stages 1-2) -----------------------------------------------------------------------

def submit_forecast(conn: Connection, cycle: dict, region: str, user: User, comment: str) -> None:
    """Submit a region's Sales Manager forecast (V1) for regional review.

    Marks it submitted, records the submitted version (snapshotting one if nothing was saved) and starts the Regional
    Manager's revision (V2) from it. The cycle moves to stage 2 once all four regions have submitted.

    Args:
        conn: database connection for this request.
        cycle: locked cycle row.
        region: region being submitted.
        user: submitting user.
        comment: reason recorded in the audit log.

    Returns:
        None
    """
    v1 = store.ensure_forecast_version(conn, cycle["id"], region, 1)
    rev_no = v1["rev_no"]
    if rev_no is None:  # submitted without any saved edit: snapshot it so the submitted version has a number
        rev_no = store.create_revision(conn, cycle["id"], region, v1, user, source="submit", comment=comment, changed=0)
    store.set_forecast_status(conn, v1["id"], "submitted", user.username)
    store.set_submitted_rev(conn, v1["id"], rev_no)
    # The Regional Manager starts from the Sales Manager's final (submitted) version.
    v2 = store.ensure_forecast_version(conn, cycle["id"], region, 2)
    store.copy_forecast(conn, v1["id"], v2["id"])
    store.set_forecast_status(conn, v2["id"], "draft", user.username)
    store.set_version_rev(conn, v2["id"], rev_no)
    store.audit(conn, user, "forecast", cycle_id=cycle["id"], region=region, version=f"V{rev_no}", comment=comment, status="submitted")
    if cycle["stage"] == 1 and _all_forecast(conn, cycle["id"], 1, "submitted"):
        _advance(conn, cycle, 2, user, "All four regions submitted forecast V1")


def approve_forecast(conn: Connection, cycle: dict, region: str, user: User, comment: str) -> None:
    """Regional Manager approves a region's forecast V2; once all four regions are approved the cycle moves to stage 3 (Planning).

    Args:
        conn: database connection for this request.
        cycle: locked cycle row.
        region: region being approved.
        user: approving user.
        comment: reason recorded in the audit log.

    Returns:
        None
    """
    v2 = store.forecast_version(conn, cycle["id"], region, 2)
    store.set_forecast_status(conn, v2["id"], "approved", user.username)
    store.audit(conn, user, "forecast", cycle_id=cycle["id"], region=region, version=f"V{v2['rev_no']}", comment=comment, status="approved")
    if _all_forecast(conn, cycle["id"], 2, "approved"):
        _advance(conn, cycle, 3, user, "All four regions approved forecast V2")


def reject_forecast(conn: Connection, cycle: dict, region: str, user: User, comment: str) -> None:
    """Regional Manager rejects a region's forecast: V1 and V2 become rejected so the Sales Manager can revise and resubmit.

    Args:
        conn: database connection for this request.
        cycle: locked cycle row.
        region: region being rejected.
        user: rejecting user.
        comment: reason for the Sales Manager.

    Returns:
        None
    """
    v1 = store.forecast_version(conn, cycle["id"], region, 1)
    v2 = store.forecast_version(conn, cycle["id"], region, 2)
    store.set_forecast_status(conn, v1["id"], "rejected", user.username)
    store.set_forecast_status(conn, v2["id"], "rejected", user.username)
    store.audit(conn, user, "forecast", cycle_id=cycle["id"], region=region, version=f"V{v2['rev_no']}", comment=comment, status="rejected")


def _all_forecast(conn: Connection, cycle_id: int, version_no: int, status: str) -> bool:
    """Check whether all four regions have the given forecast version in the given status.

    Args:
        conn: database connection for this request.
        cycle_id: planning cycle.
        version_no: 1 or 2.
        status: status to look for, e.g. "submitted".

    Returns:
        True when every region matches.
    """
    row = conn.execute(
        "SELECT count(*) AS n FROM forecast_version WHERE cycle_id = %s AND version_no = %s AND status = %s",
        (cycle_id, version_no, status),
    ).fetchone()
    return row["n"] == len(REGIONS)


# --- allocation (stages 3-5) ---------------------------------------------------------------------

def allocation_models(conn: Connection, cycle_id: int, alloc: store.AllocMap, demand_version: int = 2) -> list[dict]:
    """Facts for the business rules: one entry per product with inventory, demand and allocation per region.

    Args:
        conn: database connection for this request.
        cycle_id: planning cycle.
        alloc: allocation per region, {region: {product_id: qty}}.
        demand_version: forecast version used as demand (1 or 2).

    Returns:
        list of {"product", "inventory", "demand": {region: qty}, "allocated": {region: qty}}.
    """
    names = store.product_names(conn)
    snap = store.inventory_snapshot(conn, cycle_id)
    inventory = store.inventory_lines(conn, snap["id"] if snap else None)
    demand = store.forecast_totals(conn, cycle_id, demand_version)
    return [
        {
            "product": name,
            "inventory": inventory.get(pid, 0),
            "demand": {r: demand.get(r, {}).get(pid, 0) for r in REGIONS},
            "allocated": {r: alloc[r].get(pid, 0) for r in REGIONS},
        }
        for pid, name in names.items()
    ]


def validate_allocation(conn: Connection, cycle_id: int, alloc: store.AllocMap) -> None:
    """R-ALLOC-02 (business rules): no model may be allocated above available inventory.

    Args:
        conn: database connection for this request.
        cycle_id: planning cycle.
        alloc: allocation per region, {region: {product_id: qty}}.

    Returns:
        None

    Raises:
        HTTPException: 422 with the violations when any model is allocated above its inventory.
    """
    clients.enforce(
        "allocation",
        {"mode": "VALIDATE", "config": store.get_rule_config(conn), "models": allocation_models(conn, cycle_id, alloc)},
        "Allocation exceeds available inventory",
    )


def submit_allocation(conn: Connection, cycle: dict, user: User, comment: str) -> None:
    """Planner approves allocation V1 (stage 3) and hands it to the Regional Managers.

    Checks R-ALLOC-02, copies V1 into V2 for regional change, clears confirmations and moves the cycle to stage 4.

    Args:
        conn: database connection for this request.
        cycle: locked cycle row.
        user: Planner.
        comment: reason recorded in the audit log.

    Returns:
        None

    Raises:
        HTTPException: 422 when V1 exceeds the available inventory.
    """
    v1 = store.ensure_allocation_version(conn, cycle["id"], "1")
    validate_allocation(conn, cycle["id"], store.allocation_lines(conn, v1["id"]))
    store.set_allocation_status(conn, v1["id"], "approved")
    v2 = store.ensure_allocation_version(conn, cycle["id"], "2")
    store.copy_allocation(conn, v1["id"], v2["id"])
    store.set_allocation_status(conn, v2["id"], "draft")
    store.clear_confirmations(conn, cycle["id"])
    store.audit(conn, user, "allocation", cycle_id=cycle["id"], region=None, version="V1", comment=comment, status="approved")
    _advance(conn, cycle, 4, user, "Planner approved allocation V1")


def confirm_region(conn: Connection, cycle: dict, region: str, user: User, comment: str) -> None:
    """Regional Manager confirms allocation V2 for a region (stage 4); once all four regions confirm the cycle moves to stage 5.

    Args:
        conn: database connection for this request.
        cycle: locked cycle row.
        region: region being confirmed.
        user: confirming user.
        comment: reason recorded in the audit log.

    Returns:
        None
    """
    conn.execute(
        """INSERT INTO region_confirmation (cycle_id, region, confirmed_by) VALUES (%s, %s, %s)
           ON CONFLICT (cycle_id, region) DO UPDATE SET confirmed_by = EXCLUDED.confirmed_by, confirmed_at = now()""",
        (cycle["id"], region, user.username),
    )
    store.audit(conn, user, "allocation", cycle_id=cycle["id"], region=region, version="V2", comment=comment, status="confirmed")
    if len(store.confirmations(conn, cycle["id"])) == len(REGIONS):
        _advance(conn, cycle, 5, user, "All four regions confirmed allocation V2")


def publish(conn: Connection, cycle: dict, user: User, comment: str) -> None:
    """Head of Sales approves and publishes the final allocation.

    Re-checks R-ALLOC-02 on V2, copies it to "final", approves the still-pending transfers, records the approval and
    moves the cycle to stage 6 (Published).

    Args:
        conn: database connection for this request.
        cycle: locked cycle row.
        user: Head of Sales.
        comment: reason recorded with the approval.

    Returns:
        None

    Raises:
        HTTPException: 422 when V2 exceeds the available inventory.
    """
    v2 = store.allocation_version(conn, cycle["id"], "2")
    alloc = store.allocation_lines(conn, v2["id"])
    validate_allocation(conn, cycle["id"], alloc)
    final = store.ensure_allocation_version(conn, cycle["id"], "final")
    store.copy_allocation(conn, v2["id"], final["id"])
    store.set_allocation_status(conn, final["id"], "published")
    store.set_allocation_status(conn, v2["id"], "approved")
    # Transfers the Head did not decide one by one are approved together with the allocation.
    conn.execute(
        """UPDATE transfer_request SET status = 'approved', decided_by = %s, decided_at = now(),
                  decision_comment = 'Approved with the published allocation'
           WHERE cycle_id = %s AND status = 'pending'""",
        (user.username, cycle["id"]),
    )
    store.record_approval(conn, cycle["id"], "allocation", "APPROVE", comment, user)
    store.audit(conn, user, "approval", cycle_id=cycle["id"], region=None, version="FINAL", comment=comment, status="published")
    _advance(conn, cycle, 6, user, "Head of Sales approved and published the allocation")


def reject_final(conn: Connection, cycle: dict, user: User, comment: str) -> None:
    """Head of Sales rejects the final allocation: confirmations are cleared and the cycle returns to stage 4 (Regional change).

    Args:
        conn: database connection for this request.
        cycle: locked cycle row.
        user: Head of Sales.
        comment: reason for the Regional Managers.

    Returns:
        None
    """
    store.record_approval(conn, cycle["id"], "allocation", "REJECT", comment, user)
    store.clear_confirmations(conn, cycle["id"])
    store.audit(conn, user, "approval", cycle_id=cycle["id"], region=None, version="V2", comment=comment, status="rejected")
    _advance(conn, cycle, 4, user, "Head of Sales rejected; back to regional change")


# --- Admin overrides (FR-A2), each one audited ---------------------------------------------------

def admin_advance(conn: Connection, cycle: dict, user: User, comment: str) -> None:
    """Admin override that completes the current stage's open actions on the users' behalf so the cycle moves on.

    The override and every action it performs are audited.

    Args:
        conn: database connection for this request.
        cycle: locked cycle row.
        user: Admin.
        comment: reason for the override.

    Returns:
        None

    Raises:
        HTTPException: 409 at stage 5 (only the Head of Sales may approve) and at stage 6 (already published);
            422 when allocation V1 exceeds inventory at stage 3.
    """
    stage = cycle["stage"]
    store.audit(conn, user, "workflow", cycle_id=cycle["id"], region=None, version=STAGES[stage], comment=comment, status="override")
    if stage == 1:
        for r in REGIONS:
            v1 = store.forecast_version(conn, cycle["id"], r, 1)
            if v1 is None or v1["status"] != "submitted":
                submit_forecast(conn, cycle, r, user, f"Admin override: {comment}")
        if cycle["stage"] == 1:
            _advance(conn, cycle, 2, user, f"Admin override: {comment}")
    elif stage == 2:
        for r in REGIONS:
            v1 = store.forecast_version(conn, cycle["id"], r, 1)
            if v1 is None or v1["status"] != "submitted":
                submit_forecast(conn, cycle, r, user, f"Admin override: {comment}")
            v2 = store.forecast_version(conn, cycle["id"], r, 2)
            if v2["status"] != "approved":
                approve_forecast(conn, cycle, r, user, f"Admin override: {comment}")
    elif stage == 3:
        submit_allocation(conn, cycle, user, f"Admin override: {comment}")
    elif stage == 4:
        done = store.confirmations(conn, cycle["id"])
        for r in REGIONS:
            if r not in done:
                confirm_region(conn, cycle, r, user, f"Admin override: {comment}")
    elif stage == 5:
        raise conflict("Only the Head of Sales can approve the final allocation (R-APPR-01)")
    else:
        raise conflict("Cycle is already published; use reset to start a new cycle")


def admin_reset(conn: Connection, user: User, comment: str) -> dict:
    """Restart the selected month: a new empty cycle for the same month-year at stage 1.

    Args:
        conn: database connection for this request.
        user: Admin.
        comment: reason for the reset.

    Returns:
        The new cycle row dict.
    """
    p = store.current_cycle(conn)["period"]
    cycle = conn.execute(
        "INSERT INTO cycle (name, stage, period) VALUES (%s || ' (restart ' || to_char(now(), 'DD Mon HH24:MI') || ')', 1, %s) RETURNING *",
        (period.label(p), p),
    ).fetchone()
    store.audit(conn, user, "workflow", cycle_id=cycle["id"], region=None, version=STAGES[1], comment=comment, status="reset")
    return cycle
