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

/** Generates an .xlsx template prefilled with product names (and current values). */
export async function downloadTemplate(kind: FileKind, products: Product[], current?: CurrentValues, filename?: string) {
  const XLSX = await loadXlsx();
  const keys = valueKeys(kind);
  const rows: (string | number)[][] = [FILE_COLUMNS[kind]];
  for (const p of products) {
    const cur = current?.[String(p.id)];
    rows.push([p.name, ...keys.map((k) => cur?.[k] ?? 0)]);
  }
  const ws = XLSX.utils.aoa_to_sheet(rows);
  ws['!cols'] = [{ wch: 36 }, ...keys.map(() => ({ wch: 18 }))];
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, kind[0].toUpperCase() + kind.slice(1));
  XLSX.writeFile(wb, filename ?? `${kind}_template.xlsx`);
}

export interface ParsedRow {
  row: number; // 1-based Excel row number
  name: string;
  productId: number | null;
  values: Record<string, number | null>; // null = blank / invalid
  invalid: string[];
}

export interface ParseResult {
  rows: ParsedRow[];
  missingColumns: string[];
  duplicates: string[];
}

const norm = (s: unknown) => String(s ?? '').trim().toLowerCase().replace(/\s+/g, ' ');

/** Parses the first sheet in the browser for the before/after preview. */
export async function parseWorkbook(kind: FileKind, file: File, products: Product[]): Promise<ParseResult> {
  const XLSX = await loadXlsx();
  const wb = XLSX.read(await file.arrayBuffer(), { type: 'array' });
  const ws = wb.Sheets[wb.SheetNames[0]];
  if (!ws) return { rows: [], missingColumns: FILE_COLUMNS[kind], duplicates: [] };
  const aoa = XLSX.utils.sheet_to_json<unknown[]>(ws, { header: 1, blankrows: false, defval: null, raw: true });
  const header = (aoa[0] ?? []).map(norm);

  const findCol = (...names: string[]) => header.findIndex((h) => names.map(norm).includes(h));
  const nameIdx = findCol('Product Name');
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
  if (missingColumns.length) return { rows: [], missingColumns, duplicates: [] };

  const byName = new Map(products.map((p) => [norm(p.name), p.id]));
  const seen = new Set<string>();
  const duplicates: string[] = [];
  const rows: ParsedRow[] = [];
  aoa.slice(1).forEach((line, i) => {
    const name = String(line[nameIdx] ?? '').trim();
    if (!name) return;
    const key = norm(name);
    if (seen.has(key)) duplicates.push(name);
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
    rows.push({ row: i + 2, name, productId: byName.get(key) ?? null, values, invalid });
  });
  return { rows, missingColumns, duplicates };
}
