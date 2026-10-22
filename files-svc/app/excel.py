"""Excel sandbox: validate and parse uploaded .xlsx files into rows (values only, no formulas or macros)."""

import io
import zipfile
from datetime import datetime, UTC

from openpyxl import Workbook, load_workbook

REGIONS = ["North", "East", "West", "South"]
MAX_BYTES = 4 * 1024 * 1024
MAX_UNCOMPRESSED = 50 * 1024 * 1024
MAX_ROWS = 2000

# kind -> list of (value key, accepted header names)
COLUMNS = {
    "forecast": [("qty", ["forecast quantity", "quantity", "forecast qty", "qty"])],
    "inventory": [("qty", ["available inventory", "inventory", "quantity", "qty"])],
    "allocation": [(r, [r.lower()]) for r in REGIONS],
}


class FileRejected(Exception):
    def __init__(self, message: str, errors: list[dict] | None = None):
        super().__init__(message)
        self.errors = errors or [{"row": 0, "message": message}]


def check_container(filename: str, content: bytes) -> None:
    """Size, extension, zip magic bytes, zip-bomb and macro checks before openpyxl touches the file."""
    if not filename.lower().endswith(".xlsx"):
        raise FileRejected("Only .xlsx files are accepted")
    if len(content) > MAX_BYTES:
        raise FileRejected("File larger than 4 MB")
    if not content.startswith(b"PK\x03\x04"):
        raise FileRejected("Not a valid .xlsx (zip) file")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            names = z.namelist()
            if sum(i.file_size for i in z.infolist()) > MAX_UNCOMPRESSED:
                raise FileRejected("File expands too much when unzipped")
            if any("vbaproject" in n.lower() for n in names):
                raise FileRejected("Files with macros are not accepted")
            if "[Content_Types].xml" not in names or not any(n.startswith("xl/") for n in names):
                raise FileRejected("Not an Excel workbook")
    except zipfile.BadZipFile as e:
        raise FileRejected("Corrupt .xlsx file") from e


def _whole(value) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)) and float(value).is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def parse(kind: str, content: bytes) -> tuple[list[dict], list[dict]]:
    """Return (rows, errors). Rows: {"row", "product", "values"}. Any error rejects the whole file."""
    if kind not in COLUMNS:
        raise FileRejected(f"Unknown file kind {kind}")
    try:
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as e:  # noqa: BLE001 - any parser failure means a bad file
        raise FileRejected(f"Cannot read workbook: {e}") from e
    ws = wb.worksheets[0]
    rows_iter = ws.iter_rows(values_only=True)
    header = next(rows_iter, None)
    if not header:
        raise FileRejected("The first sheet is empty")
    index = {str(h).strip().lower(): i for i, h in enumerate(header) if h is not None}
    if "product name" not in index:
        raise FileRejected("Missing 'Product Name' column")
    cols = {}
    for key, names in COLUMNS[kind]:
        found = next((index[n] for n in names if n in index), None)
        if found is None:
            raise FileRejected(f"Missing '{names[0].title()}' column")
        cols[key] = found

    rows, errors, seen = [], [], {}
    for n, raw in enumerate(rows_iter, start=2):
        if n - 1 > MAX_ROWS:
            raise FileRejected(f"More than {MAX_ROWS} rows")
        name = raw[index["product name"]] if index["product name"] < len(raw) else None
        if name is None or str(name).strip() == "":
            if any(v not in (None, "") for v in raw):
                errors.append({"row": n, "message": "Product Name is empty"})
            continue
        product = str(name).strip()
        if product.lower() in seen:
            errors.append({"row": n, "message": f"Duplicate product '{product}' (first on row {seen[product.lower()]})"})
            continue
        seen[product.lower()] = n
        values = {}
        for key, i in cols.items():
            cell = raw[i] if i < len(raw) else None
            qty = _whole(0 if cell in (None, "") else cell)
            if qty is None or qty < 0:
                errors.append({"row": n, "message": f"{key if key != 'qty' else 'Quantity'} must be a whole number of 0 or more (got {cell!r})"})
            else:
                values[key] = qty
        if len(values) == len(cols):
            rows.append({"row": n, "product": product, "values": values})
    wb.close()
    return rows, errors


def _safe(value):
    """Neutralise spreadsheet formula injection in exported text cells."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def build(sheet: str, columns: list[str], rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet[:31] or "Sheet1"
    ws.append([_safe(c) for c in columns])
    for row in rows:
        ws.append([_safe(v) for v in row])
    ws.freeze_panes = "A2"
    ws.column_dimensions["A"].width = 32
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
