import { REGIONS, type FileKind, type Product, type QtyMap, type Region } from '../api/types';

// SheetJS is loaded on demand to keep the initial bundle small.
const loadXlsx = () => import('xlsx');

export const FILE_COLUMNS: Record<FileKind, string[]> = {
  forecast: ['Product Name', 'Forecast Quantity'],
  inventory: ['Product Name', 'Available Inventory'],
  allocation: ['Product Name', ...REGIONS],
};

/** Values for template prefill / preview "before": forecast & inventory use key `qty`. */
export type CurrentValues = Record<string, Record<string, number>>; // productId → column → qty

export function currentFromQty(products: Product[], map: QtyMap | null | undefined): CurrentValues {
  const out: CurrentValues = {};
  for (const p of products) out[String(p.id)] = { qty: map?.[String(p.id)] ?? 0 };
  return out;
}

export function currentFromMatrix(products: Product[], m: Partial<Record<Region, QtyMap>> | null | undefined): CurrentValues {
  const out: CurrentValues = {};
  for (const p of products) {
    const row: Record<string, number> = {};
    for (const r of REGIONS) row[r] = m?.[r]?.[String(p.id)] ?? 0;
    out[String(p.id)] = row;
  }
  return out;
}

export function valueKeys(kind: FileKind): string[] {
  return kind === 'allocation' ? [...REGIONS] : ['qty'];
}

export interface ParsedRow {
  row: number; // 1-based Excel row number
  name: string;
  productId: number | null;
  values: Record<string, number | null>; // null = blank / invalid
  invalid: string[];
  /** "YYYY-MM" from a Month column; null when the file has none (the selected month is used). */
  month: string | null;
}

export interface ParseResult {
  rows: ParsedRow[];
  missingColumns: string[];
  duplicates: string[];
  /** Months found in a Month column, sorted ("YYYY-MM"); empty when the file has no Month column. */
  months: string[];
}

const norm = (s: unknown) => String(s ?? '').trim().toLowerCase().replace(/[_-]+/g, ' ').replace(/\s+/g, ' ');

const MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];

/** Month-year cell → "YYYY-MM" (same formats the server accepts), or null if not a month-year. */
export function parseMonth(v: unknown): string | null {
  const fmt = (y: number, m: number) => (m >= 1 && m <= 12 && y >= 2000 && y <= 2100 ? `${y}-${String(m).padStart(2, '0')}` : null);
  if (v instanceof Date) return fmt(v.getFullYear(), v.getMonth() + 1);
  const s = String(v ?? '').trim().toLowerCase();
  let m = /^(\d{4})[-/.](\d{1,2})(?:[-/.]\d{1,2})?/.exec(s);
  if (m) return fmt(Number(m[1]), Number(m[2]));
  m = /^(\d{1,2})[-/.](\d{4})$/.exec(s);
  if (m) return fmt(Number(m[2]), Number(m[1]));
  m = /^([a-z]{3})[a-z]*[\s\-/.']*(\d{2}|\d{4})$/.exec(s);
  if (m && MONTHS.includes(m[1])) {
    const y = Number(m[2]);
    return fmt(y < 100 ? 2000 + y : y, MONTHS.indexOf(m[1]) + 1);
  }
  return null;
}

/** Parses the first sheet in the browser for the before/after preview. */
export async function parseWorkbook(kind: FileKind, file: File, products: Product[]): Promise<ParseResult> {
  const XLSX = await loadXlsx();
  const wb = XLSX.read(await file.arrayBuffer(), { type: 'array', cellDates: true }); // Month cells as Date objects
  const ws = wb.Sheets[wb.SheetNames[0]];
  if (!ws) return { rows: [], missingColumns: FILE_COLUMNS[kind], duplicates: [], months: [] };
  const aoa = XLSX.utils.sheet_to_json<unknown[]>(ws, { header: 1, blankrows: false, defval: null, raw: true });
  const header = (aoa[0] ?? []).map(norm);

  const findCol = (...names: string[]) => header.findIndex((h) => names.map(norm).includes(h));
  const nameIdx = findCol('Product Name', 'ProductName', 'Product');
  const monthIdx = findCol('Month', 'Month Year', 'MonthYear', 'Period', 'Forecast Month');
  const valueCols: { key: string; idx: number; label: string }[] =
    kind === 'forecast'
      ? [{ key: 'qty', idx: findCol('Forecast Quantity', 'Quantity'), label: 'Forecast Quantity' }]
      : kind === 'inventory'
        ? [{ key: 'qty', idx: findCol('Available Inventory'), label: 'Available Inventory' }]
        : REGIONS.map((r) => ({ key: r, idx: findCol(r), label: r }));

  const missingColumns = [
    ...(nameIdx < 0 ? ['Product Name'] : []),
    ...valueCols.filter((c) => c.idx < 0).map((c) => c.label),
  ];
  if (missingColumns.length) return { rows: [], missingColumns, duplicates: [], months: [] };

  const byName = new Map(products.map((p) => [norm(p.name), p.id]));
  const seen = new Set<string>();
  const duplicates: string[] = [];
  const rows: ParsedRow[] = [];
  aoa.slice(1).forEach((line, i) => {
    const name = String(line[nameIdx] ?? '').trim();
    if (!name) return;
    const month = monthIdx >= 0 ? parseMonth(line[monthIdx]) : null;
    const key = `${norm(name)}|${month ?? ''}`;
    if (seen.has(key)) duplicates.push(month ? `${name} (${month})` : name);
    seen.add(key);
    const values: Record<string, number | null> = {};
    const invalid: string[] = [];
    for (const c of valueCols) {
      const raw = line[c.idx];
      const n = typeof raw === 'number' ? raw : raw === null || raw === '' ? NaN : Number(String(raw).trim());
      if (Number.isInteger(n) && n >= 0) values[c.key] = n;
      else {
        values[c.key] = null;
        invalid.push(c.label);
      }
    }
    if (monthIdx >= 0 && !month) invalid.push('Month');
    rows.push({ row: i + 2, name, productId: byName.get(norm(name)) ?? null, values, invalid, month });
  });
  const months = [...new Set(rows.map((r) => r.month).filter((m): m is string => !!m))].sort();
  return { rows, missingColumns, duplicates, months };
}
