"""Excel exports built from the DB and written to SFTP /outbound through files-svc."""

import logging

from fastapi import HTTPException
from psycopg import Connection

from . import clients, store
from .auth import User
from .domain import REGIONS, SM, forbidden

log = logging.getLogger(__name__)


def table(conn: Connection, user: User, kind: str, version: str | None) -> tuple[str, str, list, list]:
    """(filename, sheet, columns, rows) for an export kind, scoped to what the caller may read."""
    cycle = store.current_cycle(conn)
    names = store.product_names(conn)
    regions = [user.region] if user.role == SM else REGIONS

    if kind == "forecast":
        vno = int(version or 1)
        if vno not in (1, 2):
            raise HTTPException(422, "version must be 1 or 2")
        data = store.forecast_totals(conn, cycle["id"], vno)
        rows = [[name] + [data.get(r, {}).get(pid, 0) for r in regions] for pid, name in names.items()]
        return f"forecast_v{vno}.xlsx", f"Forecast V{vno}", ["Product Name", *regions], rows

    if kind == "inventory":
        if user.role == SM:
            raise forbidden()
        snap = store.inventory_snapshot(conn, cycle["id"])
        inv = store.inventory_lines(conn, snap["id"] if snap else None)
        return "inventory.xlsx", "Inventory", ["Product Name", "Available Inventory"], [
            [name, inv.get(pid, 0)] for pid, name in names.items()
        ]

    if kind == "allocation":
        vno = version or "1"
        if vno not in ("1", "2", "final"):
            raise HTTPException(422, "version must be 1, 2 or final")
        av = store.allocation_version(conn, cycle["id"], vno)
        alloc = store.allocation_lines(conn, av["id"] if av else None)
        rows = []
        for pid, name in names.items():
            values = [alloc[r].get(pid, 0) for r in regions]
            rows.append([name, *values, sum(values)])
        label = "Final" if vno == "final" else f"V{vno}"
        return f"allocation_{vno}.xlsx", f"Allocation {label}", ["Product Name", *regions, "Total"], rows

    if kind == "audit":
        entries = store.audit_entries(conn, user, limit=10000)
        cols = ["Timestamp", "User", "Role", "Region", "Entity", "Version", "Product", "Before", "After", "Comment", "Status"]
        rows = [[e["ts"], e["username"], e["role"], e["region"], e["entity"], e["version"], e["product"],
                 e["beforeQty"], e["afterQty"], e["comment"], e["status"]] for e in entries]
        return "audit_trail.xlsx", "Audit", cols, rows

    raise HTTPException(404, f"Unknown export kind {kind}")


def revision_table(conn: Connection, user: User, region: str | None, rev_no: int) -> tuple[str, str, list, list]:
    """One region's forecast as it was at version V<rev_no>, in the upload template layout."""
    if region not in REGIONS:
        raise HTTPException(422, "region is required to export a forecast version")
    from .routes_workflow import visible_revision  # local import: routes_workflow imports this module

    _, lines = visible_revision(conn, user, region, rev_no)
    rows = [[name, lines.get(pid, 0)] for pid, name in store.product_names(conn).items()]
    return f"forecast_{region}_V{rev_no}.xlsx", f"{region} V{rev_no}", ["Product Name", "Forecast Quantity"], rows


def write_published_export(conn: Connection, user: User) -> None:
    """Best-effort copy of the published allocation to SFTP /outbound; failures are audited, not raised."""
    cycle = store.current_cycle(conn)
    try:
        filename, sheet, cols, rows = table(conn, user, "allocation", "final")
        clients.export_file(f"published_{filename}", sheet, cols, rows)
        status, message = "processed", "Published allocation written to /outbound"
    except HTTPException as e:
        log.warning("published export failed: %s", e.detail)
        status, message = "export_failed", str(e.detail)
    conn.execute(
        "INSERT INTO file_ingest (path, kind, status, message, uploaded_by) VALUES (%s, %s, %s, %s, %s)",
        ("/files/outbound/published_allocation_final.xlsx", "export", status, message, user.username),
    )
    store.audit(conn, user, "file", cycle_id=cycle["id"], region=None, version="FINAL", comment=message, status=status)
    conn.commit()
