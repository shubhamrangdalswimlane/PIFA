"""SQL data access. Quantity maps are {product_id: qty}; a missing product means 0."""

from psycopg import Connection

from .auth import User
from .domain import REGIONS

QtyMap = dict[int, int]


# --- cycle and products ---------------------------------------------------------------------------

def current_cycle(conn: Connection) -> dict:
    row = conn.execute("SELECT * FROM cycle ORDER BY id DESC LIMIT 1").fetchone()
    if row is None:
        row = conn.execute(
            "INSERT INTO cycle (name, stage) VALUES ('Cycle ' || to_char(now(), 'YYYY-MM'), 1) RETURNING *"
        ).fetchone()
    return row


def lock_cycle(conn: Connection) -> dict:
    """Current cycle row locked for the rest of the transaction, so stage changes serialize."""
    cycle = current_cycle(conn)
    return conn.execute("SELECT * FROM cycle WHERE id = %s FOR UPDATE", (cycle["id"],)).fetchone()


def set_stage(conn: Connection, cycle_id: int, stage: int) -> None:
    conn.execute("UPDATE cycle SET stage = %s WHERE id = %s", (stage, cycle_id))


def products(conn: Connection) -> list[dict]:
    return conn.execute("SELECT id, name FROM product ORDER BY id").fetchall()


def product_names(conn: Connection) -> dict[int, str]:
    return {p["id"]: p["name"] for p in products(conn)}


def product_ids_by_name(conn: Connection) -> dict[str, int]:
    return {p["name"].strip().lower(): p["id"] for p in products(conn)}


def ensure_product(conn: Connection, name: str) -> int:
    row = conn.execute(
        "INSERT INTO product (name) VALUES (%s) ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id",
        (name.strip(),),
    ).fetchone()
    return row["id"]


# --- forecast -------------------------------------------------------------------------------------

def forecast_version(conn: Connection, cycle_id: int, region: str, version_no: int) -> dict | None:
    return conn.execute(
        "SELECT * FROM forecast_version WHERE cycle_id = %s AND region = %s AND version_no = %s",
        (cycle_id, region, version_no),
    ).fetchone()


def ensure_forecast_version(conn: Connection, cycle_id: int, region: str, version_no: int) -> dict:
    row = forecast_version(conn, cycle_id, region, version_no)
    if row is None:
        row = conn.execute(
            "INSERT INTO forecast_version (cycle_id, region, version_no) VALUES (%s, %s, %s) RETURNING *",
            (cycle_id, region, version_no),
        ).fetchone()
    return row


def set_forecast_status(conn: Connection, version_id: int, status: str, username: str) -> None:
    conn.execute(
        "UPDATE forecast_version SET status = %s, updated_by = %s, updated_at = now() WHERE id = %s",
        (status, username, version_id),
    )


def forecast_lines(conn: Connection, version_id: int) -> QtyMap:
    rows = conn.execute("SELECT product_id, qty FROM forecast_line WHERE version_id = %s", (version_id,))
    return {r["product_id"]: r["qty"] for r in rows}


def write_forecast_lines(conn: Connection, version_id: int, values: QtyMap) -> None:
    for pid, qty in values.items():
        conn.execute(
            """INSERT INTO forecast_line (version_id, product_id, qty) VALUES (%s, %s, %s)
               ON CONFLICT (version_id, product_id) DO UPDATE SET qty = EXCLUDED.qty""",
            (version_id, pid, qty),
        )


def copy_forecast(conn: Connection, src_version_id: int, dst_version_id: int) -> None:
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
    conn.execute("UPDATE forecast_version SET rev_no = %s WHERE id = %s", (rev_no, version_id))


def revisions(conn: Connection, cycle_id: int, region: str, created_by: str | None = None) -> list[dict]:
    """Versions of a region's forecast, newest first; only those `created_by` a user when given."""
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
    rev = conn.execute(
        "SELECT id FROM forecast_revision WHERE cycle_id = %s AND region = %s AND rev_no = %s", (cycle_id, region, rev_no)
    ).fetchone()
    if rev is None:
        return None
    rows = conn.execute("SELECT product_id, qty FROM forecast_revision_line WHERE revision_id = %s", (rev["id"],))
    return {r["product_id"]: r["qty"] for r in rows}


def set_submitted_rev(conn: Connection, version_id: int, rev_no: int) -> None:
    conn.execute("UPDATE forecast_version SET submitted_rev = %s WHERE id = %s", (rev_no, version_id))


def submitted_lines(conn: Connection, fv: dict) -> QtyMap:
    """The Sales Manager forecast as submitted (what reviewers and planning see); the working copy until first submit."""
    if fv.get("submitted_rev"):
        lines = revision_lines(conn, fv["cycle_id"], fv["region"], fv["submitted_rev"])
        if lines is not None:
            return lines
    return forecast_lines(conn, fv["id"])


def latest_rejection(conn: Connection, cycle_id: int, region: str) -> dict | None:
    """Most recent Regional Manager rejection of a region's forecast (shown to its Sales Manager)."""
    row = conn.execute(
        """SELECT username, comment, ts FROM audit_log
           WHERE cycle_id = %s AND region = %s AND entity = 'forecast' AND status = 'rejected'
           ORDER BY id DESC LIMIT 1""",
        (cycle_id, region),
    ).fetchone()
    return {"by": row["username"], "comment": row["comment"], "at": row["ts"].isoformat()} if row else None


def forecast_totals(conn: Connection, cycle_id: int, version_no: int) -> dict[str, dict[int, int]]:
    """{region: {product_id: qty}} for regions that have this version (V1 = the submitted Sales Manager forecast)."""
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
    return conn.execute(
        "SELECT * FROM inventory_snapshot WHERE cycle_id = %s ORDER BY id DESC LIMIT 1", (cycle_id,)
    ).fetchone()


def inventory_lines(conn: Connection, snapshot_id: int | None) -> QtyMap:
    if snapshot_id is None:
        return {}
    rows = conn.execute("SELECT product_id, qty FROM inventory_line WHERE snapshot_id = %s", (snapshot_id,))
    return {r["product_id"]: r["qty"] for r in rows}


def new_inventory_snapshot(conn: Connection, cycle_id: int, username: str, source_file: str | None) -> dict:
    """New snapshot carrying over the previous lines (each upload is its own snapshot)."""
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
    for pid, qty in values.items():
        conn.execute(
            """INSERT INTO inventory_line (snapshot_id, product_id, qty) VALUES (%s, %s, %s)
               ON CONFLICT (snapshot_id, product_id) DO UPDATE SET qty = EXCLUDED.qty""",
            (snapshot_id, pid, qty),
        )


# --- allocation -----------------------------------------------------------------------------------

AllocMap = dict[str, QtyMap]  # {region: {product_id: qty}}


def allocation_version(conn: Connection, cycle_id: int, version_no: str) -> dict | None:
    return conn.execute(
        "SELECT * FROM allocation_version WHERE cycle_id = %s AND version_no = %s", (cycle_id, version_no)
    ).fetchone()


def ensure_allocation_version(conn: Connection, cycle_id: int, version_no: str) -> dict:
    row = allocation_version(conn, cycle_id, version_no)
    if row is None:
        row = conn.execute(
            "INSERT INTO allocation_version (cycle_id, version_no) VALUES (%s, %s) RETURNING *", (cycle_id, version_no)
        ).fetchone()
    return row


def set_allocation_status(conn: Connection, version_id: int, status: str) -> None:
    conn.execute("UPDATE allocation_version SET status = %s, updated_at = now() WHERE id = %s", (status, version_id))


def allocation_lines(conn: Connection, version_id: int | None) -> AllocMap:
    out: AllocMap = {r: {} for r in REGIONS}
    if version_id is None:
        return out
    rows = conn.execute("SELECT product_id, region, qty FROM allocation_line WHERE version_id = %s", (version_id,))
    for r in rows:
        out[r["region"]][r["product_id"]] = r["qty"]
    return out


def write_allocation_line(conn: Connection, version_id: int, product_id: int, region: str, qty: int) -> None:
    conn.execute(
        """INSERT INTO allocation_line (version_id, product_id, region, qty) VALUES (%s, %s, %s, %s)
           ON CONFLICT (version_id, product_id, region) DO UPDATE SET qty = EXCLUDED.qty""",
        (version_id, product_id, region, qty),
    )


def copy_allocation(conn: Connection, src_version_id: int, dst_version_id: int) -> None:
    conn.execute("DELETE FROM allocation_line WHERE version_id = %s", (dst_version_id,))
    conn.execute(
        """INSERT INTO allocation_line (version_id, product_id, region, qty)
           SELECT %s, product_id, region, qty FROM allocation_line WHERE version_id = %s""",
        (dst_version_id, src_version_id),
    )


# --- confirmations, transfers, approvals -----------------------------------------------------------

def confirmations(conn: Connection, cycle_id: int) -> dict[str, dict]:
    rows = conn.execute("SELECT * FROM region_confirmation WHERE cycle_id = %s", (cycle_id,))
    return {r["region"]: r for r in rows}


def clear_confirmations(conn: Connection, cycle_id: int) -> None:
    conn.execute("DELETE FROM region_confirmation WHERE cycle_id = %s", (cycle_id,))


def transfer_row(conn: Connection, transfer_id: int) -> dict | None:
    return conn.execute(
        """SELECT t.*, p.name AS product FROM transfer_request t JOIN product p ON p.id = t.product_id
           WHERE t.id = %s""",
        (transfer_id,),
    ).fetchone()


def transfers(conn: Connection, cycle_id: int) -> list[dict]:
    return conn.execute(
        """SELECT t.*, p.name AS product FROM transfer_request t JOIN product p ON p.id = t.product_id
           WHERE t.cycle_id = %s ORDER BY t.id DESC""",
        (cycle_id,),
    ).fetchall()


def record_approval(conn: Connection, cycle_id: int, entity: str, decision: str, comment: str | None, user: User) -> None:
    conn.execute(
        "INSERT INTO approval (cycle_id, entity, decision, comment, decided_by) VALUES (%s, %s, %s, %s, %s)",
        (cycle_id, entity, decision, comment, user.username),
    )


def get_rule_config(conn: Connection) -> dict:
    cfg = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM rule_config")}
    return {"baselinePct": cfg.get("baselinePct", 25), "sharing": cfg.get("sharing", "UNMET_DEMAND")}


# --- audit (append-only) ----------------------------------------------------------------------------

def audit_entries(conn: Connection, user: User, role: str | None = None, entity: str | None = None,
                  region: str | None = None, q: str | None = None, limit: int = 500) -> list[dict]:
    """Audit trail for the current cycle (plus cycle-less rows), scoped to the caller's visibility:
    Sales Manager, Regional Manager and Planner see only their own changes; Head and Admin see all."""
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
        f"""SELECT a.*, p.name AS product FROM audit_log a LEFT JOIN product p ON p.id = a.product_id
            WHERE {' AND '.join(where)} ORDER BY a.id DESC LIMIT %s""",
        args,
    )
    return [
        {
            "id": r["id"], "ts": r["ts"].isoformat(), "username": r["username"], "role": r["role"], "region": r["region"],
            "entity": r["entity"], "version": r["version"], "productId": r["product_id"], "product": r["product"],
            "beforeQty": r["before_qty"], "afterQty": r["after_qty"], "comment": r["comment"], "status": r["status"],
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
