"""SQL data access. Quantity maps are {product_id: qty}; a missing product means 0."""

from datetime import date

from fastapi import HTTPException
from psycopg import Connection

from . import period
from .auth import User
from .domain import REGIONS

QtyMap = dict[int, int]


# --- cycle and products ---------------------------------------------------------------------------

def current_cycle(conn: Connection) -> dict:
    """Cycle of the selected month-year (X-Period); without one, the most recently created cycle.

    Args:
        conn: database connection for this request.

    Returns:
        The cycle row as a dict (id, name, stage, period, ...). When the database has no cycle at all, one is
        created for the current month.

    Raises:
        HTTPException: 404 when the selected month has no planning cycle yet.
    """
    p = period.current()
    if p is not None:
        row = cycle_for_period(conn, p)
        if row is None:
            raise HTTPException(404, f"There is no planning cycle for {period.label(p)} yet")
        return row
    row = conn.execute("SELECT * FROM cycle ORDER BY id DESC LIMIT 1").fetchone()
    return row if row is not None else ensure_period_cycle(conn, date.today().replace(day=1))


def cycle_for_period(conn: Connection, p: date) -> dict | None:
    """Find the current (latest) cycle of a month-year.

    Args:
        conn: database connection for this request.
        p: first day of the month.

    Returns:
        The cycle row dict, or None when that month has not been opened.
    """
    return conn.execute("SELECT * FROM cycle WHERE period = %s ORDER BY id DESC LIMIT 1", (p,)).fetchone()


def ensure_period_cycle(conn: Connection, p: date) -> dict:
    """The month's current cycle, created at stage 1 when the month is new.

    Args:
        conn: database connection for this request.
        p: first day of the month.

    Returns:
        The cycle row dict.
    """
    row = cycle_for_period(conn, p)
    if row is None:
        row = conn.execute(
            "INSERT INTO cycle (name, stage, period) VALUES (%s, 1, %s) RETURNING *", (period.label(p), p)
        ).fetchone()
    return row


def periods(conn: Connection) -> list[dict]:
    """Every month-year with its current cycle, oldest first.

    Args:
        conn: database connection for this request.

    Returns:
        list of cycle row dicts, one per month-year.
    """
    return conn.execute("SELECT DISTINCT ON (period) * FROM cycle ORDER BY period, id DESC").fetchall()


def lock_cycle(conn: Connection) -> dict:
    """Current cycle row locked for the rest of the transaction, so stage changes serialize.

    Args:
        conn: database connection for this request.

    Returns:
        The locked cycle row dict.

    Raises:
        HTTPException: 404 when the selected month has no planning cycle yet.
    """
    cycle = current_cycle(conn)
    return conn.execute("SELECT * FROM cycle WHERE id = %s FOR UPDATE", (cycle["id"],)).fetchone()


def set_stage(conn: Connection, cycle_id: int, stage: int) -> None:
    """Move a cycle to another workflow stage (1-6); the caller records the audit entry.

    Args:
        conn: database connection for this request.
        cycle_id: cycle to update.
        stage: new stage number.

    Returns:
        None
    """
    conn.execute("UPDATE cycle SET stage = %s WHERE id = %s", (stage, cycle_id))


def products(conn: Connection) -> list[dict]:
    """List all printer models.

    Args:
        conn: database connection for this request.

    Returns:
        list of {"id", "name"} ordered by id.
    """
    return conn.execute("SELECT id, name FROM product ORDER BY id").fetchall()


def product_names(conn: Connection) -> dict[int, str]:
    """Map product IDs to product names.

    Args:
        conn: database connection for this request.

    Returns:
        {product_id: name} in id order.
    """
    return {p["id"]: p["name"] for p in products(conn)}


def product_ids_by_name(conn: Connection) -> dict[str, int]:
    """Map normalised product names (trimmed, lower-case) to IDs, for matching rows of uploaded files.

    Args:
        conn: database connection for this request.

    Returns:
        {normalised name: product_id}.
    """
    return {p["name"].strip().lower(): p["id"] for p in products(conn)}


def ensure_product(conn: Connection, name: str) -> int:
    """Add a product by name when it is new (new names found in uploaded files).

    Args:
        conn: database connection for this request.
        name: product name; surrounding whitespace is trimmed.

    Returns:
        The product ID (existing or newly created).
    """
    row = conn.execute(
        "INSERT INTO product (name) VALUES (%s) ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id",
        (name.strip(),),
    ).fetchone()
    return row["id"]


# --- forecast -------------------------------------------------------------------------------------

def forecast_version(conn: Connection, cycle_id: int, region: str, version_no: int) -> dict | None:
    """Get a region's stage forecast in a cycle: version 1 is the Sales Manager's forecast, version 2 the Regional Manager's revision.

    Args:
        conn: database connection for this request.
        cycle_id: planning cycle.
        region: region name.
        version_no: 1 or 2.

    Returns:
        The forecast_version row dict, or None when it does not exist.
    """
    return conn.execute(
        "SELECT * FROM forecast_version WHERE cycle_id = %s AND region = %s AND version_no = %s",
        (cycle_id, region, version_no),
    ).fetchone()


def ensure_forecast_version(conn: Connection, cycle_id: int, region: str, version_no: int) -> dict:
    """Get a region's stage forecast in a cycle, creating it when missing.

    Args:
        conn: database connection for this request.
        cycle_id: planning cycle.
        region: region name.
        version_no: 1 (Sales Manager) or 2 (Regional Manager).

    Returns:
        The forecast_version row dict.
    """
    row = forecast_version(conn, cycle_id, region, version_no)
    if row is None:
        row = conn.execute(
            "INSERT INTO forecast_version (cycle_id, region, version_no) VALUES (%s, %s, %s) RETURNING *",
            (cycle_id, region, version_no),
        ).fetchone()
    return row


def set_forecast_status(conn: Connection, version_id: int, status: str, username: str) -> None:
    """Set a stage forecast's status and record who changed it.

    Args:
        conn: database connection for this request.
        version_id: forecast_version id.
        status: new status: draft, submitted, approved or rejected.
        username: user making the change.

    Returns:
        None
    """
    conn.execute(
        "UPDATE forecast_version SET status = %s, updated_by = %s, updated_at = now() WHERE id = %s",
        (status, username, version_id),
    )


def forecast_lines(conn: Connection, version_id: int) -> QtyMap:
    """Working quantities of a stage forecast.

    Args:
        conn: database connection for this request.
        version_id: forecast_version id.

    Returns:
        {product_id: qty}.
    """
    rows = conn.execute("SELECT product_id, qty FROM forecast_line WHERE version_id = %s", (version_id,))
    return {r["product_id"]: r["qty"] for r in rows}


def write_forecast_lines(conn: Connection, version_id: int, values: QtyMap) -> None:
    """Insert or update quantities in a stage forecast's working copy.

    Args:
        conn: database connection for this request.
        version_id: forecast_version id.
        values: {product_id: qty} to write.

    Returns:
        None
    """
    for pid, qty in values.items():
        conn.execute(
            """INSERT INTO forecast_line (version_id, product_id, qty) VALUES (%s, %s, %s)
               ON CONFLICT (version_id, product_id) DO UPDATE SET qty = EXCLUDED.qty""",
            (version_id, pid, qty),
        )


def copy_forecast(conn: Connection, src_version_id: int, dst_version_id: int) -> None:
    """Replace a stage forecast's lines with a copy of another's (e.g. the submitted V1 into the Regional Manager's V2).

    Args:
        conn: database connection for this request.
        src_version_id: forecast_version to copy from.
        dst_version_id: forecast_version to overwrite.

    Returns:
        None
    """
    conn.execute("DELETE FROM forecast_line WHERE version_id = %s", (dst_version_id,))
    conn.execute(
        "INSERT INTO forecast_line (version_id, product_id, qty) SELECT %s, product_id, qty FROM forecast_line WHERE version_id = %s",
        (dst_version_id, src_version_id),
    )


def create_revision(conn: Connection, cycle_id: int, region: str, fv: dict, user: User, *, source: str,
                    comment: str, changed: int, file_name: str | None = None, lines: QtyMap | None = None,
                    applied: bool = True) -> int:
    """Snapshot a region forecast as its next revision (V1, V2, ...). Caller holds the cycle lock.

    By default the snapshot is the stage version's current lines and becomes its current revision.
    With applied=False, `lines` is stored as a history-only version and the working copy is untouched.

    Args:
        conn: database connection for this request.
        cycle_id: planning cycle.
        region: region name.
        fv: stage forecast_version row the version belongs to.
        user: author of the version.
        source: what created it: edit, upload, submit or restore.
        comment: reason given by the author.
        changed: number of changed lines.
        file_name: uploaded file name, when the version came from Excel.
        lines: quantities to snapshot; defaults to fv's current lines.
        applied: whether the version becomes fv's current version.

    Returns:
        The new version number (the n of V<n>).
    """
    rev_no = conn.execute(
        "SELECT coalesce(max(rev_no), 0) + 1 AS n FROM forecast_revision WHERE cycle_id = %s AND region = %s",
        (cycle_id, region),
    ).fetchone()["n"]
    if lines is None:
        lines = forecast_lines(conn, fv["id"])
    rev = conn.execute(
        """INSERT INTO forecast_revision (cycle_id, region, rev_no, stage, source, file_name, created_by, role, comment,
                                          changed, total, applied)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (cycle_id, region, rev_no, fv["version_no"], source, file_name, user.username, user.role, comment, changed,
         sum(lines.values()), applied),
    ).fetchone()
    for pid, qty in lines.items():
        conn.execute("INSERT INTO forecast_revision_line (revision_id, product_id, qty) VALUES (%s, %s, %s)", (rev["id"], pid, qty))
    if applied:
        set_version_rev(conn, fv["id"], rev_no)
    return rev_no


def set_version_rev(conn: Connection, version_id: int, rev_no: int | None) -> None:
    """Point a stage forecast at the version its working copy now holds.

    Args:
        conn: database connection for this request.
        version_id: forecast_version id.
        rev_no: version number, or None.

    Returns:
        None
    """
    conn.execute("UPDATE forecast_version SET rev_no = %s WHERE id = %s", (rev_no, version_id))


def revisions(conn: Connection, cycle_id: int, region: str, created_by: str | None = None) -> list[dict]:
    """Versions of a region's forecast, newest first; only those `created_by` a user when given.

    Args:
        conn: database connection for this request.
        cycle_id: planning cycle.
        region: region name.
        created_by: username to filter on; None returns every version.

    Returns:
        list of {"revNo", "label", "stage", "source", "fileName", "createdBy", "role", "comment", "changed", "total",
        "applied", "createdAt"}.
    """
    rows = conn.execute(
        """SELECT * FROM forecast_revision WHERE cycle_id = %s AND region = %s AND (%s::text IS NULL OR created_by = %s)
           ORDER BY rev_no DESC""",
        (cycle_id, region, created_by, created_by),
    )
    return [
        {
            "revNo": r["rev_no"], "label": f"V{r['rev_no']}", "stage": r["stage"], "source": r["source"],
            "fileName": r["file_name"], "createdBy": r["created_by"], "role": r["role"], "comment": r["comment"],
            "changed": r["changed"], "total": r["total"], "applied": r["applied"], "createdAt": r["created_at"].isoformat(),
        }
        for r in rows
    ]


def revision_lines(conn: Connection, cycle_id: int, region: str, rev_no: int) -> QtyMap | None:
    """Quantities stored in one forecast version.

    Args:
        conn: database connection for this request.
        cycle_id: planning cycle.
        region: region name.
        rev_no: version number.

    Returns:
        {product_id: qty}, or None when the version does not exist.
    """
    rev = conn.execute(
        "SELECT id FROM forecast_revision WHERE cycle_id = %s AND region = %s AND rev_no = %s", (cycle_id, region, rev_no)
    ).fetchone()
    if rev is None:
        return None
    rows = conn.execute("SELECT product_id, qty FROM forecast_revision_line WHERE revision_id = %s", (rev["id"],))
    return {r["product_id"]: r["qty"] for r in rows}


def set_submitted_rev(conn: Connection, version_id: int, rev_no: int) -> None:
    """Record which version the Sales Manager submitted for regional review.

    Args:
        conn: database connection for this request.
        version_id: id of the region's V1 forecast_version.
        rev_no: submitted version number.

    Returns:
        None
    """
    conn.execute("UPDATE forecast_version SET submitted_rev = %s WHERE id = %s", (rev_no, version_id))


def submitted_lines(conn: Connection, fv: dict) -> QtyMap:
    """The Sales Manager forecast as submitted (what reviewers and planning see); the working copy until first submit.

    Args:
        conn: database connection for this request.
        fv: the region's V1 forecast_version row.

    Returns:
        {product_id: qty}.
    """
    if fv.get("submitted_rev"):
        lines = revision_lines(conn, fv["cycle_id"], fv["region"], fv["submitted_rev"])
        if lines is not None:
            return lines
    return forecast_lines(conn, fv["id"])


def latest_rejection(conn: Connection, cycle_id: int, region: str) -> dict | None:
    """Most recent Regional Manager rejection of a region's forecast (shown to its Sales Manager).

    Args:
        conn: database connection for this request.
        cycle_id: planning cycle.
        region: region name.

    Returns:
        {"by", "comment", "at"} of the latest rejection, or None when there is none.
    """
    row = conn.execute(
        """SELECT username, comment, ts FROM audit_log
           WHERE cycle_id = %s AND region = %s AND entity = 'forecast' AND status = 'rejected'
           ORDER BY id DESC LIMIT 1""",
        (cycle_id, region),
    ).fetchone()
    return {"by": row["username"], "comment": row["comment"], "at": row["ts"].isoformat()} if row else None


def forecast_totals(conn: Connection, cycle_id: int, version_no: int) -> dict[str, dict[int, int]]:
    """{region: {product_id: qty}} for regions that have this version (V1 = the submitted Sales Manager forecast).

    Args:
        conn: database connection for this request.
        cycle_id: planning cycle.
        version_no: 1 (submitted Sales Manager forecast) or 2 (Regional Manager revision).

    Returns:
        {region: {product_id: qty}}.
    """
    if version_no == 1:
        rows = conn.execute("SELECT * FROM forecast_version WHERE cycle_id = %s AND version_no = 1", (cycle_id,))
        return {fv["region"]: submitted_lines(conn, fv) for fv in rows.fetchall()}
    out: dict[str, dict[int, int]] = {}
    rows = conn.execute(
        """SELECT fv.region, fl.product_id, fl.qty FROM forecast_version fv
           LEFT JOIN forecast_line fl ON fl.version_id = fv.id
           WHERE fv.cycle_id = %s AND fv.version_no = %s""",
        (cycle_id, version_no),
    )
    for r in rows:
        region_map = out.setdefault(r["region"], {})
        if r["product_id"] is not None:
            region_map[r["product_id"]] = r["qty"]
    return out


# --- inventory ------------------------------------------------------------------------------------

def inventory_snapshot(conn: Connection, cycle_id: int) -> dict | None:
    """Latest inventory snapshot of a cycle.

    Args:
        conn: database connection for this request.
        cycle_id: planning cycle.

    Returns:
        The snapshot row dict (id, source_file, uploaded_by, created_at, ...), or None when no inventory was entered.
    """
    return conn.execute(
        "SELECT * FROM inventory_snapshot WHERE cycle_id = %s ORDER BY id DESC LIMIT 1", (cycle_id,)
    ).fetchone()


def inventory_lines(conn: Connection, snapshot_id: int | None) -> QtyMap:
    """Available inventory per product in a snapshot.

    Args:
        conn: database connection for this request.
        snapshot_id: inventory snapshot id; None means there is no snapshot.

    Returns:
        {product_id: qty}; empty when snapshot_id is None.
    """
    if snapshot_id is None:
        return {}
    rows = conn.execute("SELECT product_id, qty FROM inventory_line WHERE snapshot_id = %s", (snapshot_id,))
    return {r["product_id"]: r["qty"] for r in rows}


def new_inventory_snapshot(conn: Connection, cycle_id: int, username: str, source_file: str | None) -> dict:
    """New snapshot carrying over the previous lines (each upload is its own snapshot).

    Args:
        conn: database connection for this request.
        cycle_id: planning cycle.
        username: user uploading or editing the inventory.
        source_file: uploaded file name; None for dashboard edits.

    Returns:
        The new snapshot row dict.
    """
    prev = inventory_snapshot(conn, cycle_id)
    snap = conn.execute(
        "INSERT INTO inventory_snapshot (cycle_id, source_file, uploaded_by) VALUES (%s, %s, %s) RETURNING *",
        (cycle_id, source_file, username),
    ).fetchone()
    if prev:
        conn.execute(
            "INSERT INTO inventory_line (snapshot_id, product_id, qty) SELECT %s, product_id, qty FROM inventory_line WHERE snapshot_id = %s",
            (snap["id"], prev["id"]),
        )
    return snap


def write_inventory_lines(conn: Connection, snapshot_id: int, values: QtyMap) -> None:
    """Insert or update quantities in an inventory snapshot.

    Args:
        conn: database connection for this request.
        snapshot_id: inventory snapshot id.
        values: {product_id: qty} to write.

    Returns:
        None
    """
    for pid, qty in values.items():
        conn.execute(
            """INSERT INTO inventory_line (snapshot_id, product_id, qty) VALUES (%s, %s, %s)
               ON CONFLICT (snapshot_id, product_id) DO UPDATE SET qty = EXCLUDED.qty""",
            (snapshot_id, pid, qty),
        )


# --- allocation -----------------------------------------------------------------------------------

AllocMap = dict[str, QtyMap]  # {region: {product_id: qty}}


def allocation_version(conn: Connection, cycle_id: int, version_no: str) -> dict | None:
    """Get an allocation version of a cycle: "1" (Planner draft), "2" (regional change and transfers) or "final" (published).

    Args:
        conn: database connection for this request.
        cycle_id: planning cycle.
        version_no: "1", "2" or "final".

    Returns:
        The allocation_version row dict, or None when it does not exist.
    """
    return conn.execute(
        "SELECT * FROM allocation_version WHERE cycle_id = %s AND version_no = %s", (cycle_id, version_no)
    ).fetchone()


def ensure_allocation_version(conn: Connection, cycle_id: int, version_no: str) -> dict:
    """Get an allocation version of a cycle, creating it when missing.

    Args:
        conn: database connection for this request.
        cycle_id: planning cycle.
        version_no: "1", "2" or "final".

    Returns:
        The allocation_version row dict.
    """
    row = allocation_version(conn, cycle_id, version_no)
    if row is None:
        row = conn.execute(
            "INSERT INTO allocation_version (cycle_id, version_no) VALUES (%s, %s) RETURNING *", (cycle_id, version_no)
        ).fetchone()
    return row


def set_allocation_status(conn: Connection, version_id: int, status: str) -> None:
    """Set an allocation version's status.

    Args:
        conn: database connection for this request.
        version_id: allocation_version id.
        status: new status: draft, approved or published.

    Returns:
        None
    """
    conn.execute("UPDATE allocation_version SET status = %s, updated_at = now() WHERE id = %s", (status, version_id))


def allocation_lines(conn: Connection, version_id: int | None) -> AllocMap:
    """Allocated units per region and product for an allocation version.

    Args:
        conn: database connection for this request.
        version_id: allocation_version id; None means the version does not exist yet.

    Returns:
        {region: {product_id: qty}} with every region present.
    """
    out: AllocMap = {r: {} for r in REGIONS}
    if version_id is None:
        return out
    rows = conn.execute("SELECT product_id, region, qty FROM allocation_line WHERE version_id = %s", (version_id,))
    for r in rows:
        out[r["region"]][r["product_id"]] = r["qty"]
    return out


def write_allocation_line(conn: Connection, version_id: int, product_id: int, region: str, qty: int) -> None:
    """Insert or update one allocation cell.

    Args:
        conn: database connection for this request.
        version_id: allocation_version id.
        product_id: printer model.
        region: region name.
        qty: allocated units.

    Returns:
        None
    """
    conn.execute(
        """INSERT INTO allocation_line (version_id, product_id, region, qty) VALUES (%s, %s, %s, %s)
           ON CONFLICT (version_id, product_id, region) DO UPDATE SET qty = EXCLUDED.qty""",
        (version_id, product_id, region, qty),
    )


def copy_allocation(conn: Connection, src_version_id: int, dst_version_id: int) -> None:
    """Replace an allocation version's lines with a copy of another's (e.g. V1 into V2, V2 into final).

    Args:
        conn: database connection for this request.
        src_version_id: allocation_version to copy from.
        dst_version_id: allocation_version to overwrite.

    Returns:
        None
    """
    conn.execute("DELETE FROM allocation_line WHERE version_id = %s", (dst_version_id,))
    conn.execute(
        """INSERT INTO allocation_line (version_id, product_id, region, qty)
           SELECT %s, product_id, region, qty FROM allocation_line WHERE version_id = %s""",
        (dst_version_id, src_version_id),
    )


# --- confirmations, transfers, approvals -----------------------------------------------------------

def confirmations(conn: Connection, cycle_id: int) -> dict[str, dict]:
    """Regional Manager confirmations of allocation V2 (stage 4) in a cycle.

    Args:
        conn: database connection for this request.
        cycle_id: planning cycle.

    Returns:
        {region: region_confirmation row} for the regions that have confirmed.
    """
    rows = conn.execute("SELECT * FROM region_confirmation WHERE cycle_id = %s", (cycle_id,))
    return {r["region"]: r for r in rows}


def clear_confirmations(conn: Connection, cycle_id: int) -> None:
    """Withdraw every regional confirmation of a cycle (after a transfer, an undo or a final rejection).

    Args:
        conn: database connection for this request.
        cycle_id: planning cycle.

    Returns:
        None
    """
    conn.execute("DELETE FROM region_confirmation WHERE cycle_id = %s", (cycle_id,))


def transfer_row(conn: Connection, transfer_id: int) -> dict | None:
    """Load one transfer request with its product name.

    Args:
        conn: database connection for this request.
        transfer_id: transfer_request id.

    Returns:
        The transfer_request row dict plus "product", or None when it does not exist.
    """
    return conn.execute(
        """SELECT t.*, p.name AS product FROM transfer_request t JOIN product p ON p.id = t.product_id
           WHERE t.id = %s""",
        (transfer_id,),
    ).fetchone()


def transfers(conn: Connection, cycle_id: int) -> list[dict]:
    """All transfer requests of a cycle, newest first, with product names.

    Args:
        conn: database connection for this request.
        cycle_id: planning cycle.

    Returns:
        list of transfer_request row dicts plus "product".
    """
    return conn.execute(
        """SELECT t.*, p.name AS product FROM transfer_request t JOIN product p ON p.id = t.product_id
           WHERE t.cycle_id = %s ORDER BY t.id DESC""",
        (cycle_id,),
    ).fetchall()


def record_approval(conn: Connection, cycle_id: int, entity: str, decision: str, comment: str | None, user: User) -> None:
    """Record a Head of Sales decision on the final allocation.

    Args:
        conn: database connection for this request.
        cycle_id: planning cycle.
        entity: what was decided, e.g. "allocation".
        decision: APPROVE or REJECT.
        comment: reason given, if any.
        user: user making the decision.

    Returns:
        None
    """
    conn.execute(
        "INSERT INTO approval (cycle_id, entity, decision, comment, decided_by) VALUES (%s, %s, %s, %s, %s)",
        (cycle_id, entity, decision, comment, user.username),
    )


def get_rule_config(conn: Connection) -> dict:
    """Current allocation rule settings chosen by the Admin, with defaults for unset keys.

    Args:
        conn: database connection for this request.

    Returns:
        {"baselinePct": int, "sharing": "UNMET_DEMAND" | "PROPORTIONAL"}.
    """
    cfg = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM rule_config")}
    return {"baselinePct": cfg.get("baselinePct", 25), "sharing": cfg.get("sharing", "PROPORTIONAL")}


# --- audit (append-only) ----------------------------------------------------------------------------

def audit_entries(conn: Connection, user: User, role: str | None = None, entity: str | None = None,
                  region: str | None = None, q: str | None = None, limit: int = 500, month: str | None = None) -> list[dict]:
    """Audit trail scoped to the caller's visibility: Sales Manager, Regional Manager and Planner see only their
    own changes; Head and Admin see all. `month`: None = the selected month's cycle, "all" = every month,
    "YYYY-MM" (or any month format) = that month's cycles. Every entry carries its month-year.

    Args:
        conn: database connection for this request.
        user: signed-in caller (from the JWT); the role decides which entries are visible.
        role: only entries made by this role.
        entity: only entries about this entity (forecast, inventory, allocation, transfer, approval, workflow, file).
        region: only entries for this region.
        q: free-text search over comment, username, product name and status.
        limit: maximum number of entries.
        month: month filter as described above.

    Returns:
        list of {"id", "ts", "username", "role", "region", "entity", "version", "productId", "product", "beforeQty",
        "afterQty", "comment", "status", "period", "periodLabel"}, newest first.

    Raises:
        HTTPException: 422 when `month` is not a valid month-year; 404 when the selected month has no cycle.
    """
    if month == "all":
        where, args = ["TRUE"], []
    elif month:
        try:
            where, args = ["c.period = %s"], [period.parse(month)]
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
    else:
        where, args = ["(a.cycle_id = %s OR a.cycle_id IS NULL)"], [current_cycle(conn)["id"]]
    if user.own_history_only:
        where.append("a.username = %s")
        args.append(user.username)
    if region:
        where.append("a.region = %s")
        args.append(region)
    if role:
        where.append("a.role = %s")
        args.append(role)
    if entity:
        where.append("a.entity = %s")
        args.append(entity)
    if q:
        where.append("(a.comment ILIKE %s OR a.username ILIKE %s OR p.name ILIKE %s OR a.status ILIKE %s)")
        args += [f"%{q}%"] * 4
    args.append(limit)
    rows = conn.execute(
        f"""SELECT a.*, p.name AS product, c.period FROM audit_log a
            LEFT JOIN product p ON p.id = a.product_id LEFT JOIN cycle c ON c.id = a.cycle_id
            WHERE {' AND '.join(where)} ORDER BY a.id DESC LIMIT %s""",
        args,
    )
    return [
        {
            "id": r["id"], "ts": r["ts"].isoformat(), "username": r["username"], "role": r["role"], "region": r["region"],
            "entity": r["entity"], "version": r["version"], "productId": r["product_id"], "product": r["product"],
            "beforeQty": r["before_qty"], "afterQty": r["after_qty"], "comment": r["comment"], "status": r["status"],
            "period": period.key(r["period"]) if r["period"] else None,
            "periodLabel": period.label(r["period"]) if r["period"] else None,
        }
        for r in rows
    ]


def audit(
    conn: Connection,
    user: User | None,
    entity: str,
    *,
    cycle_id: int | None,
    region: str | None = None,
    version: str | None = None,
    product_id: int | None = None,
    before: int | None = None,
    after: int | None = None,
    comment: str | None = None,
    status: str | None = None,
    username: str | None = None,
    role: str | None = None,
) -> None:
    """Append one entry to the audit log (entries are never updated or deleted).

    The actor's name, role and region default to `user`, or to "system" when there is no user.

    Args:
        conn: database connection for this request.
        user: acting user, or None for system and service actions.
        entity: what changed: forecast, inventory, allocation, transfer, approval, workflow or file.
        cycle_id: cycle the entry belongs to, or None.
        region: affected region; defaults to the user's region.
        version: version label, e.g. "V3", "FINAL" or a stage key.
        product_id: affected product, if any.
        before: quantity before the change.
        after: quantity after the change.
        comment: reason or description.
        status: status or outcome recorded with the entry.
        username: overrides the recorded username (e.g. uploads reported by files-svc).
        role: overrides the recorded role.

    Returns:
        None
    """
    conn.execute(
        """INSERT INTO audit_log (username, role, region, cycle_id, entity, version, product_id,
                                  before_qty, after_qty, comment, status)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            username or (user.username if user else "system"),
            role or (user.role if user else "SYSTEM"),
            region if region is not None else (user.region if user else None),
            cycle_id,
            entity,
            version,
            product_id,
            before,
            after,
            comment,
            status,
        ),
    )
