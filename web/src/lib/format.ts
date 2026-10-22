import type { QtyMap, Region, Role, StageNumber } from '../api/types';

const nf = new Intl.NumberFormat('en-US');

export function fmtQty(n: number | null | undefined): string {
  return n === null || n === undefined || Number.isNaN(n) ? '—' : nf.format(n);
}

export function fmtDelta(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  if (n === 0) return '0';
  return `${n > 0 ? '+' : '−'}${nf.format(Math.abs(n))}`;
}

export function deltaClass(n: number | null | undefined): string {
  if (!n) return 'delta-zero';
  return n > 0 ? 'delta-pos' : 'delta-neg';
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { year: 'numeric', month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

export const ROLE_LABEL: Record<Role, string> = {
  SALES_MANAGER: 'Sales Manager',
  REGIONAL_MANAGER: 'Regional Manager',
  PLANNER: 'Planner',
  HEAD_OF_SALES: 'Head of Sales',
  ADMIN: 'Admin',
};

export const ROLE_ROUTE: Record<Role, string> = {
  SALES_MANAGER: '/sales',
  REGIONAL_MANAGER: '/regional',
  PLANNER: '/planner',
  HEAD_OF_SALES: '/head',
  ADMIN: '/admin',
};

export const STAGES: { n: StageNumber; label: string; actor: string }[] = [
  { n: 1, label: 'Forecast input', actor: 'Sales Managers' },
  { n: 2, label: 'Regional review', actor: 'Regional Managers' },
  { n: 3, label: 'Planning', actor: 'Planner' },
  { n: 4, label: 'Regional change', actor: 'Regional Managers' },
  { n: 5, label: 'Final approval', actor: 'Head of Sales' },
  { n: 6, label: 'Published', actor: '' },
];

export const REGION_CLASS: Record<Region, string> = {
  North: 'r-north',
  East: 'r-east',
  West: 'r-west',
  South: 'r-south',
};

/** Sum of a quantity map (missing → 0). */
export function sumMap(m: QtyMap | null | undefined): number {
  if (!m) return 0;
  let s = 0;
  for (const v of Object.values(m)) s += Number(v) || 0;
  return s;
}

export function qtyOf(m: QtyMap | null | undefined, productId: number): number | null {
  if (!m) return null;
  return m[String(productId)] ?? 0;
}
