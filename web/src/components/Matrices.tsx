import { useCallback, useMemo, type ReactNode } from 'react';
import type { AllocationResponse, ForecastResponse, Product, QtyMap, Region } from '../api/types';
import { EditableGrid, type CellChange, type Eff, type GridColumn, type RowTone } from './EditableGrid';

export type FcVersion = 'v1' | 'v2';
export type AllocVersion = 'v1' | 'v2' | 'final';

const sumKeys = (eff: Eff, keys: string[]): number | null => {
  let s: number | null = null;
  for (const k of keys) {
    const v = eff(k);
    if (v !== null) s = (s ?? 0) + v;
  }
  return s;
};

/** All regions side by side for one forecast version; V2 shows Δ vs V1 per region. */
export function ForecastRegionsGrid({
  forecast,
  version,
  ownRegion,
  editableRegion,
  onSave,
  toolbar,
}: {
  forecast: ForecastResponse;
  version: FcVersion;
  ownRegion?: Region | null;
  /** Region whose V2 column is editable (Regional Manager at stage 2). */
  editableRegion?: Region | null;
  onSave?: (changes: CellChange[], comment: string) => Promise<unknown>;
  toolbar?: ReactNode;
}) {
  const columns = useMemo<GridColumn[]>(() => {
    const cols: GridColumn[] = [];
    const valueKeys: string[] = [];
    for (const r of forecast.regions) {
      const own = r === ownRegion;
      if (version === 'v1') {
        const s = forecast.status[r];
        cols.push({ type: 'qty', key: r, label: (s?.v1SubmittedRev ?? s?.v1Rev) ? `${r} · V${s?.v1SubmittedRev ?? s?.v1Rev}` : r, values: forecast.v1[r], highlight: own });
        valueKeys.push(r);
      } else {
        const s = forecast.status[r];
        cols.push({ type: 'qty', key: `v1:${r}`, label: (s?.v1SubmittedRev ?? s?.v1Rev) ? `Sales V${s?.v1SubmittedRev ?? s?.v1Rev}` : 'Sales', values: forecast.v1[r], group: r, highlight: own });
        cols.push({
          type: 'qty',
          key: r,
          label: s?.v2Rev ? `Regional V${s.v2Rev}` : 'Regional',
          values: forecast.v2[r],
          group: r,
          highlight: own,
          editable: !!onSave && editableRegion === r,
        });
        cols.push({
          type: 'calc',
          key: `d:${r}`,
          label: 'Δ',
          group: r,
          highlight: own,
          tone: 'delta',
          calc: (eff) => {
            const a = eff(`v1:${r}`);
            const b = eff(r);
            return a === null || b === null ? null : b - a;
          },
        });
        valueKeys.push(r);
      }
    }
    cols.push({ type: 'calc', key: 'total', label: version === 'v2' ? 'Total regional' : 'Total sales', group: version === 'v2' ? 'All regions' : undefined, calc: (eff) => sumKeys(eff, valueKeys) });
    if (version === 'v2') {
      cols.push({
        type: 'calc',
        key: 'total:d',
        label: 'Δ',
        group: 'All regions',
        tone: 'delta',
        calc: (eff) => {
          const t = sumKeys(eff, valueKeys);
          const t1 = sumKeys(eff, forecast.regions.map((r) => `v1:${r}`));
          return t === null || t1 === null ? null : t - t1;
        },
      });
    }
    return cols;
  }, [forecast, version, ownRegion, editableRegion, onSave]);

  return (
    <EditableGrid
      products={forecast.products}
      columns={columns}
      onSave={onSave}
      saveTitle={`Save forecast ${version.toUpperCase()} changes${editableRegion ? ` — ${editableRegion}` : ''}`}
      toolbar={toolbar}
    />
  );
}

export function allocationVersionMap(a: AllocationResponse | undefined, v: AllocVersion) {
  if (!a) return null;
  return v === 'v1' ? a.v1 : v === 'v2' ? a.v2 : a.final;
}

/** Allocation matrix with optional inventory / balance and Δ vs V1. */
export function AllocationGrid({
  products,
  allocation,
  version,
  inventory,
  ownRegion,
  editable,
  onSave,
  toolbar,
  showDelta = true,
}: {
  products: Product[];
  allocation: AllocationResponse;
  version: AllocVersion;
  inventory?: QtyMap | null;
  ownRegion?: Region | null;
  editable?: boolean;
  onSave?: (changes: CellChange[], comment: string) => Promise<unknown>;
  toolbar?: ReactNode;
  showDelta?: boolean;
}) {
  const matrix = allocationVersionMap(allocation, version);
  const regions = allocation.regions;
  const withDelta = showDelta && version !== 'v1' && !!allocation.v1 && !!matrix;

  const columns = useMemo<GridColumn[]>(() => {
    const cols: GridColumn[] = [];
    for (const r of regions) {
      const own = r === ownRegion;
      if (withDelta) cols.push({ type: 'qty', key: `v1:${r}`, label: 'V1', values: allocation.v1?.[r] ?? {}, group: r, highlight: own });
      cols.push({
        type: 'qty',
        key: r,
        label: withDelta ? (version === 'final' ? 'Final' : 'V2') : r,
        values: matrix ? (matrix[r] ?? {}) : null,
        group: withDelta ? r : undefined,
        highlight: own,
        editable: !!editable && !!onSave,
      });
      if (withDelta)
        cols.push({
          type: 'calc',
          key: `d:${r}`,
          label: 'Δ',
          group: r,
          highlight: own,
          tone: 'delta',
          calc: (eff) => {
            const a = eff(`v1:${r}`);
            const b = eff(r);
            return a === null || b === null ? null : b - a;
          },
        });
    }
    const g = withDelta ? 'Totals' : undefined;
    cols.push({ type: 'calc', key: 'allocated', label: 'Allocated', group: g, calc: (eff) => sumKeys(eff, regions) });
    if (inventory !== undefined) {
      cols.push({ type: 'qty', key: 'inventory', label: 'Inventory', group: g, values: inventory });
      cols.push({
        type: 'calc',
        key: 'balance',
        label: 'Balance',
        group: g,
        tone: 'balance',
        title: 'Inventory − allocated',
        calc: (eff) => {
          const inv = eff('inventory');
          const al = eff('allocated');
          return inv === null || al === null ? null : inv - al;
        },
      });
    }
    return cols;
  }, [regions, ownRegion, withDelta, allocation.v1, version, matrix, editable, onSave, inventory]);

  const rowTone = useCallback(
    (eff: Eff): RowTone => {
      const b = eff('balance');
      return b !== null && b < 0 ? 'danger' : null;
    },
    [],
  );

  return (
    <EditableGrid
      products={products}
      columns={columns}
      onSave={onSave}
      rowTone={inventory !== undefined ? rowTone : undefined}
      rowNote={inventory !== undefined ? overNote : undefined}
      saveTitle="Save allocation V1 changes"
      toolbar={toolbar}
      emptyText="No products."
    />
  );
}

function overNote(eff: Eff) {
  const b = eff('balance');
  return b !== null && b < 0 ? <span className="flag">over inventory by {Math.abs(b)}</span> : null;
}
