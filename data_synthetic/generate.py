"""Generate synthetic upload files for PIFA.

Outputs (same column layout as the in-app upload templates):
  forecast_<Region>.xlsx  - Sales Manager forecast V1 per region: Product Name, Forecast Quantity
  inventory.xlsx          - Planner inventory: Product Name, Available Inventory
  summary.xlsx            - Forecast vs inventory per product (reference only, not for upload)
  forecast_<Region>_monthly.xlsx, inventory_monthly.xlsx
                          - Product_Name, Month, quantity for Nov 2026 - Jan 2027 (one upload fills three months)

Inventory is deliberately mixed: about half the products have less stock than the total
forecast (constrained, so allocation is proportional) and half have more (surplus stays
unallocated). Run: python data_synthetic/generate.py [--seed 42]
"""

import argparse
import random
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill

REGIONS = ["North", "East", "West", "South"]
# Same names as the seeded products (pifa_api/migrations/002_seed.sql) so uploads match.
PRODUCTS = [
    "Printer Model A", "Printer Model B", "Printer Model C", "Printer Model D",
    "Mono Laser L100", "Mono Laser L200", "Mono Laser MFP L300", "Color Laser C100",
    "Color Laser C200", "Color Laser MFP C300", "Inkjet Home I100", "Inkjet Home I200",
    "Inkjet Office I300", "Ink Tank T100", "Ink Tank T200", "Photo Inkjet P100",
    "Wide Format W100", "Wide Format W200", "Mobile Printer M100", "Label Printer B100",
]
# Regional demand profile: some regions buy more than others.
REGION_WEIGHT = {"North": 1.2, "East": 1.0, "West": 0.9, "South": 0.7}
OUT = Path(__file__).resolve().parent
BOLD = Font(bold=True)
SHORT = PatternFill("solid", fgColor="FDE2E1")
SURPLUS = PatternFill("solid", fgColor="E3F4E8")


def save(path: Path, header: list[str], rows: list[list]) -> None:
    """Write one simple upload-style workbook: bold frozen header row, then the data rows.

    Args:
        path: Output .xlsx file path (overwritten).
        header: Header row labels, e.g. ["Product Name", "Forecast Quantity"].
        rows: Data rows, one list of cell values per row.

    Returns:
        None
    """
    wb = Workbook()
    ws = wb.active
    ws.append(header)
    for c in ws[1]:
        c.font = BOLD
    for r in rows:
        ws.append(r)
    ws.column_dimensions["A"].width = 26
    for col in "BCDEFGH":
        ws.column_dimensions[col].width = 18
    ws.freeze_panes = "A2"
    wb.save(path)


def main(seed: int) -> None:
    """Generate all synthetic files: per-region forecasts, inventory, the reference summary and the monthly files.

    Inventory is set below total forecast for a random half of the products (constrained) and above it for the rest.

    Args:
        seed: Random seed, so the same seed always produces the same files.

    Returns:
        None
    """
    rng = random.Random(seed)

    # Base demand per product (volume differs by product class), then per-region noise.
    forecast = {r: {} for r in REGIONS}
    for p in PRODUCTS:
        base = rng.randint(40, 250)
        for r in REGIONS:
            forecast[r][p] = max(0, round(base * REGION_WEIGHT[r] * rng.uniform(0.6, 1.4)))

    # Half the products short of demand, half in surplus (shuffled so it is not by position).
    shortage = set(rng.sample(PRODUCTS, len(PRODUCTS) // 2))
    inventory, summary = {}, []
    for p in PRODUCTS:
        total = sum(forecast[r][p] for r in REGIONS)
        ratio = rng.uniform(0.55, 0.92) if p in shortage else rng.uniform(1.08, 1.5)
        inventory[p] = round(total * ratio)
        diff = inventory[p] - total
        summary.append([p, *(forecast[r][p] for r in REGIONS), total, inventory[p], diff,
                        "Short (constrained)" if diff < 0 else "Surplus"])

    for r in REGIONS:
        save(OUT / f"forecast_{r}.xlsx", ["Product Name", "Forecast Quantity"], [[p, forecast[r][p]] for p in PRODUCTS])
    save(OUT / "inventory.xlsx", ["Product Name", "Available Inventory"], [[p, inventory[p]] for p in PRODUCTS])

    header = ["Product Name", *REGIONS, "Total Forecast", "Available Inventory", "Inventory - Forecast", "Status"]
    save(OUT / "summary.xlsx", header, summary)
    wb = load_workbook(OUT / "summary.xlsx")
    ws = wb.active
    for row in ws.iter_rows(min_row=2):
        fill = SHORT if row[-1].value.startswith("Short") else SURPLUS
        for c in row:
            c.fill = fill
    wb.save(OUT / "summary.xlsx")

    short = sum(1 for s in summary if s[-2] < 0)
    print(f"seed {seed}: {len(PRODUCTS)} products, {short} short of forecast, {len(PRODUCTS) - short} in surplus")
    print(f"total forecast {sum(s[5] for s in summary)}, total inventory {sum(inventory.values())}")

    multi_month(rng, forecast, inventory)


# Months covered by the multi-month files (one Month column; each month is planned separately).
MONTHS = ["2026-11", "2026-12", "2027-01"]
# Products that appear only in the monthly files, to show new product names being added on upload.
NEW_PRODUCTS = ["Printer Model E", "Eco Laser L400"]


def multi_month(rng: random.Random, forecast: dict, inventory: dict) -> None:
    """forecast_<Region>_monthly.xlsx and inventory_monthly.xlsx: Product_Name, Month, quantity for 3 months.

    Month 1 uses the single-month numbers; later months drift by -15%..+20% (seasonality), and two new
    products start in the second month. Inventory again mixes short and surplus products per month.

    Args:
        rng: The seeded random generator shared with `main`.
        forecast: Single-month forecast per region and product, `{region: {product: qty}}`.
        inventory: Single-month available inventory per product, `{product: qty}`.

    Returns:
        None
    """
    products = PRODUCTS + NEW_PRODUCTS
    for r in REGIONS:
        rows = []
        for i, month in enumerate(MONTHS):
            for p in products:
                if p in NEW_PRODUCTS and i == 0:
                    continue
                base = forecast[r].get(p) or rng.randint(20, 120)
                qty = base if i == 0 else max(0, round(base * rng.uniform(0.85, 1.2)))
                rows.append([p, month, qty])
        save(OUT / f"forecast_{r}_monthly.xlsx", ["Product_Name", "Month", "Forecast Quantity"], rows)
    rows = []
    for i, month in enumerate(MONTHS):
        for p in products:
            if p in NEW_PRODUCTS and i == 0:
                continue
            base = inventory.get(p) or rng.randint(150, 400)
            rows.append([p, month, base if i == 0 else max(0, round(base * rng.uniform(0.8, 1.15)))])
    save(OUT / "inventory_monthly.xlsx", ["Product_Name", "Month", "Available Inventory"], rows)
    print(f"monthly files: {', '.join(MONTHS)}; new products {', '.join(NEW_PRODUCTS)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    main(ap.parse_args().seed)
