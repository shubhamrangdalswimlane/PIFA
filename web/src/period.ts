// The month-year the whole app works on (e.g. "2026-11"). Every API call sends it as the X-Period header.

const KEY = 'pifa.period';
let current: string | null = null;
try {
  current = localStorage.getItem(KEY);
} catch {
  /* storage unavailable */
}

export function getPeriod(): string | null {
  return current;
}

export function setPeriod(period: string): void {
  current = period;
  try {
    localStorage.setItem(KEY, period);
  } catch {
    /* storage unavailable */
  }
}

/** "2026-11" → "Nov 2026" */
export function periodLabel(period: string): string {
  const [y, m] = period.split('-').map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString(undefined, { month: 'short', year: 'numeric' });
}
