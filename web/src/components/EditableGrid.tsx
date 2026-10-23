import { memo, useCallback, useMemo, useState, type ReactNode } from 'react';
import type { Product, QtyMap } from '../api/types';
import { deltaClass, fmtDelta, fmtQty } from '../lib/format';
import { CommentModal } from './Modal';

/** Value lookup for the current row: effective value incl. pending edits. */
export type Eff = (key: string) => number | null;

export interface QtyColumn {
  type: 'qty';
  key: string;
  label: string;
  /** Map productId → qty. `null`/`undefined` = version not available (shows —). */
  values: QtyMap | null | undefined;
  editable?: boolean;
  highlight?: boolean;
  group?: string;
  title?: string;
}

export interface CalcColumn {
  type: 'calc';
  key: string;
  label: string;
  calc: (eff: Eff) => number | null;
  /** delta: +/- colouring; balance: red when negative. */
  tone?: 'delta' | 'balance' | 'plain';
  highlight?: boolean;
  group?: string;
  title?: string;
}

export type GridColumn = QtyColumn | CalcColumn;

export interface CellChange {
  key: string;
  productId: number;
  qty: number;
}

export type RowTone = 'danger' | 'warn' | null;

interface EditableGridProps {
  products: Product[];
  columns: GridColumn[];
  /** Called with all pending changes + comment. Must reject on failure. */
  onSave?: (changes: CellChange[], comment: string) => Promise<unknown>;
  rowTone?: (eff: Eff) => RowTone;
  /** Short description of the save target, shown in the comment modal. */
  saveTitle?: string;
  toolbar?: ReactNode;
  emptyText?: string;
  /** Extra text cell rendered after the product name (e.g. flags). */
  rowNote?: (eff: Eff, product: Product) => ReactNode;
}

type Pending = Record<string, Record<string, string>>; // productId → colKey → raw input

/**
 * Checks that a cell entry is a whole number of 0 or more.
 * @param s - raw input
 * @returns true when valid
 */
const isValidQty = (s: string) => /^\d+$/.test(s.trim());

/**
 * Builds the value lookup for one product row: pending (valid) edits win over stored values, and
 * calculated columns are computed from those; results are cached per column.
 * @param columns - grid columns
 * @param productId - product of the row
 * @param pendingRow - raw pending inputs of the row by column key
 * @returns the `Eff` lookup for the row
 */
function makeEff(columns: GridColumn[], productId: number, pendingRow: Record<string, string> | undefined): Eff {
  const cache = new Map<string, number | null>();
  const byKey = new Map(columns.map((c) => [c.key, c]));
  /**
   * @param key - column key
   * @returns the effective value of that column for the row, or null when not available
   */
  const eff: Eff = (key) => {
    if (cache.has(key)) return cache.get(key)!;
    const col = byKey.get(key);
    let v: number | null = null;
    if (col?.type === 'qty') {
      const raw = pendingRow?.[key];
      if (raw !== undefined && isValidQty(raw)) v = Number(raw);
      else v = col.values ? (col.values[String(productId)] ?? 0) : null;
    } else if (col?.type === 'calc') {
      v = col.calc(eff);
    }
    cache.set(key, v);
    return v;
  };
  return eff;
}

/**
 * CSS class for a calculated cell: delta colouring, or red for a negative balance.
 * @param col - column of the cell
 * @param v - cell value
 * @returns the CSS class, or ''
 */
function toneClass(col: GridColumn, v: number | null): string {
  if (col.type !== 'calc') return '';
  if (col.tone === 'delta') return deltaClass(v);
  if (col.tone === 'balance' && v !== null && v < 0) return 'delta-neg';
  return '';
}

/**
 * Formats a cell value: signed for delta columns, plain quantity otherwise.
 * @param col - column of the cell
 * @param v - cell value
 * @returns the display text
 */
function fmtCell(col: GridColumn, v: number | null): string {
  return col.type === 'calc' && col.tone === 'delta' ? fmtDelta(v) : fmtQty(v);
}

interface RowProps {
  product: Product;
  columns: GridColumn[];
  pendingRow: Record<string, string> | undefined;
  onEdit: (productId: number, key: string, raw: string, original: number | null) => void;
  rowTone?: (eff: Eff) => RowTone;
  rowNote?: (eff: Eff, product: Product) => ReactNode;
}

/**
 * One product row of the grid: editable inputs for editable quantity columns (marked pending / invalid),
 * formatted values for the others; memoised so typing re-renders only the edited row.
 * @param props.product - product of the row
 * @param props.pendingRow - raw pending inputs of the row
 * @param props.onEdit - called on every keystroke in an editable cell
 * @param props.rowTone - optional row highlighting (danger / warn)
 * @param props.rowNote - optional extra content after the product name
 * @returns the rendered table row
 */
const GridRow = memo(function GridRow({ product, columns, pendingRow, onEdit, rowTone, rowNote }: RowProps) {
  const eff = makeEff(columns, product.id, pendingRow);
  const tone = rowTone?.(eff);
  return (
    <tr className={tone ? `row-${tone}` : undefined}>
      <th scope="row" className="col-product">
        <span className="product-name">{product.name}</span>
        {rowNote?.(eff, product)}
      </th>
      {columns.map((col) => {
        const hl = col.highlight ? ' col-hl' : '';
        if (col.type === 'qty' && col.editable) {
          const original = col.values ? (col.values[String(product.id)] ?? 0) : null;
          const raw = pendingRow?.[col.key];
          const invalid = raw !== undefined && !isValidQty(raw);
          return (
            <td key={col.key} className={`num editable${raw !== undefined ? ' pending' : ''}${invalid ? ' invalid' : ''}${hl}`}>
              <input
                className="cell-input"
                inputMode="numeric"
                aria-label={`${product.name} ${col.label}`}
                value={raw ?? (original === null ? '' : String(original))}
                onChange={(e) => onEdit(product.id, col.key, e.target.value, original)}
                onFocus={(e) => e.target.select()}
              />
            </td>
          );
        }
        const v = eff(col.key);
        return (
          <td key={col.key} className={`num ${toneClass(col, v)}${hl}`}>
            {fmtCell(col, v)}
          </td>
        );
      })}
    </tr>
  );
});

/**
 * Products-as-rows grid with optional editable quantity columns. Edits are
 * kept as pending cells; "Save" opens a comment modal (empty comment cannot be
 * saved, FR-C2). Delta and computed columns update live from pending values.
 * Also offers a product filter, an "only flagged" filter and a totals row.
 * @param props.products - rows of the grid
 * @param props.columns - quantity and calculated columns
 * @param props.onSave - receives all valid pending changes and the comment; must reject on failure
 * @param props.rowTone - flags rows (danger / warn) from their effective values
 * @param props.saveTitle - title of the comment dialog
 * @param props.toolbar - extra toolbar content (e.g. upload / export buttons)
 * @returns the rendered grid with toolbar
 */
export function EditableGrid({
  products,
  columns,
  onSave,
  rowTone,
  saveTitle = 'Save changes',
  toolbar,
  emptyText = 'No products.',
  rowNote,
}: EditableGridProps) {
  const [pending, setPending] = useState<Pending>({});
  const [filter, setFilter] = useState('');
  const [onlyFlagged, setOnlyFlagged] = useState(false);
  const [commentOpen, setCommentOpen] = useState(false);

  /**
   * Records a cell edit as pending; typing the original value back removes the pending entry.
   * @param productId - product of the edited row
   * @param key - column key
   * @param raw - raw input text
   * @param original - stored value of the cell
   * @returns nothing
   */
  const onEdit = useCallback((productId: number, key: string, raw: string, original: number | null) => {
    setPending((p) => {
      const pid = String(productId);
      const row = { ...(p[pid] ?? {}) };
      const trimmed = raw.trim();
      if (isValidQty(trimmed) && Number(trimmed) === original) delete row[key];
      else row[key] = raw;
      const next = { ...p };
      if (Object.keys(row).length) next[pid] = row;
      else delete next[pid];
      return next;
    });
  }, []);

  const changes = useMemo(() => {
    const out: CellChange[] = [];
    let invalid = 0;
    for (const [pid, row] of Object.entries(pending)) {
      for (const [key, raw] of Object.entries(row)) {
        if (isValidQty(raw)) out.push({ key, productId: Number(pid), qty: Number(raw.trim()) });
        else invalid++;
      }
    }
    return { out, invalid };
  }, [pending]);

  const totals = useMemo(() => {
    const t: Record<string, number | null> = {};
    let flagged = 0;
    for (const col of columns) t[col.key] = null;
    for (const p of products) {
      const eff = makeEff(columns, p.id, pending[String(p.id)]);
      if (rowTone?.(eff)) flagged++;
      for (const col of columns) {
        const v = eff(col.key);
        if (v !== null) t[col.key] = (t[col.key] ?? 0) + v;
      }
    }
    return { t, flagged };
  }, [columns, products, pending, rowTone]);

  const visible = useMemo(() => {
    const f = filter.trim().toLowerCase();
    return products.filter((p) => {
      if (f && !p.name.toLowerCase().includes(f)) return false;
      if (onlyFlagged && rowTone && !rowTone(makeEff(columns, p.id, pending[String(p.id)]))) return false;
      return true;
    });
  }, [products, filter, onlyFlagged, rowTone, columns, pending]);

  const hasGroups = columns.some((c) => c.group);
  const groups = useMemo(() => {
    const gs: { label: string; span: number; highlight: boolean }[] = [];
    for (const c of columns) {
      const label = c.group ?? '';
      const last = gs[gs.length - 1];
      if (last && last.label === label && label !== '') {
        last.span++;
        last.highlight ||= !!c.highlight;
      } else gs.push({ label, span: 1, highlight: !!c.highlight });
    }
    return gs;
  }, [columns]);

  const editable = columns.some((c) => c.type === 'qty' && c.editable) && !!onSave;
  const pendingCount = changes.out.length + changes.invalid;

  return (
    <div className="grid-block">
      <div className="grid-toolbar">
        <input
          className="search"
          type="search"
          placeholder={`Filter ${products.length} products…`}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          aria-label="Filter products"
        />
        {rowTone && (
          <label className="check">
            <input type="checkbox" checked={onlyFlagged} onChange={(e) => setOnlyFlagged(e.target.checked)} />
            Only flagged ({totals.flagged})
          </label>
        )}
        <div className="spacer" />
        {toolbar}
        {editable && (
          <>
            <button className="btn" disabled={pendingCount === 0} onClick={() => setPending({})}>
              Discard
            </button>
            <button
              className="btn btn-primary"
              disabled={changes.out.length === 0 || changes.invalid > 0}
              title={changes.invalid > 0 ? 'Fix invalid cells (whole numbers ≥ 0 only)' : undefined}
              onClick={() => setCommentOpen(true)}
            >
              Save {changes.out.length || ''} change{changes.out.length === 1 ? '' : 's'}…
            </button>
          </>
        )}
      </div>
      {changes.invalid > 0 && <p className="hint danger">Quantities must be whole numbers of 0 or more (R-FC-01).</p>}
      <div className="grid-wrap">
        <table className="grid">
          <thead>
            {hasGroups && (
              <tr className="group-row">
                <th className="col-product" />
                {groups.map((g, i) => (
                  <th key={i} colSpan={g.span} className={`${g.label ? 'group' : ''}${g.highlight ? ' col-hl' : ''}`}>
                    {g.label}
                  </th>
                ))}
              </tr>
            )}
            <tr>
              <th className="col-product">Product</th>
              {columns.map((c) => (
                <th key={c.key} className={`num${c.highlight ? ' col-hl' : ''}`} title={c.title}>
                  {c.label}
                  {c.type === 'qty' && c.editable && <span className="edit-mark" title="Editable"> ✎</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((p) => (
              <GridRow
                key={p.id}
                product={p}
                columns={columns}
                pendingRow={pending[String(p.id)]}
                onEdit={onEdit}
                rowTone={rowTone}
                rowNote={rowNote}
              />
            ))}
            {visible.length === 0 && (
              <tr>
                <td colSpan={columns.length + 1} className="empty">
                  {products.length === 0 ? emptyText : 'No products match the filter.'}
                </td>
              </tr>
            )}
          </tbody>
          <tfoot>
            <tr>
              <th className="col-product">Total ({products.length})</th>
              {columns.map((c) => {
                const v = totals.t[c.key];
                return (
                  <td key={c.key} className={`num ${toneClass(c, v)}${c.highlight ? ' col-hl' : ''}`}>
                    {fmtCell(c, v)}
                  </td>
                );
              })}
            </tr>
          </tfoot>
        </table>
      </div>
      {onSave && (
        <CommentModal
          open={commentOpen}
          title={saveTitle}
          confirmLabel={`Save ${changes.out.length} change${changes.out.length === 1 ? '' : 's'}`}
          onClose={() => setCommentOpen(false)}
          onSubmit={async (comment) => {
            await onSave(changes.out, comment);
            setPending({});
          }}
        >
          <ChangeSummary changes={changes.out} products={products} columns={columns} />
        </CommentModal>
      )}
    </div>
  );
}

/**
 * Before/after table of the pending changes shown in the save dialog (first 50 rows).
 * @param props.changes - pending changes
 * @param props.products - products, for names
 * @param props.columns - columns, for labels and "before" values
 * @returns the rendered summary
 */
function ChangeSummary({ changes, products, columns }: { changes: CellChange[]; products: Product[]; columns: GridColumn[] }) {
  const names = useMemo(() => new Map(products.map((p) => [p.id, p.name])), [products]);
  const cols = useMemo(() => new Map(columns.map((c) => [c.key, c])), [columns]);
  return (
    <div className="change-summary">
      <table className="mini">
        <thead>
          <tr>
            <th>Product</th>
            <th>Column</th>
            <th className="num">Before</th>
            <th className="num">After</th>
          </tr>
        </thead>
        <tbody>
          {changes.slice(0, 50).map((c) => {
            const col = cols.get(c.key);
            const before = col?.type === 'qty' && col.values ? (col.values[String(c.productId)] ?? 0) : null;
            return (
              <tr key={`${c.productId}-${c.key}`}>
                <td>{names.get(c.productId)}</td>
                <td>{col?.group ? `${col.group} ${col.label}` : col?.label}</td>
                <td className="num">{fmtQty(before)}</td>
                <td className="num strong">{fmtQty(c.qty)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {changes.length > 50 && <p className="muted small">…and {changes.length - 50} more</p>}
    </div>
  );
}
