import { useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import { useApiMutation, useRevision, useRevisions } from '../api/hooks';
import type { ForecastRevision, Product, Region } from '../api/types';
import { deltaClass, fmtDelta, fmtQty, fmtTime } from '../lib/format';
import { CommentModal } from './Modal';
import { useToast } from './Toast';
import { Empty, Loading, Panel, QueryError } from './ui';

const SOURCE_LABEL: Record<string, string> = { edit: 'Dashboard edit', upload: 'Excel upload', submit: 'Submitted', restore: 'Restored' };
const STAGE_LABEL: Record<number, string> = { 1: 'Sales Manager', 2: 'Regional Manager' };

interface Props {
  region: Region;
  products: Product[];
  /** Version numbers the working copies hold now, marked in the list. */
  currentSales?: number | null;
  currentRegional?: number | null;
  /** Version the Sales Manager submitted. */
  submitted?: number | null;
  /** When set, each row offers "Restore" into the caller's working copy. */
  canRestore?: boolean;
  restoreHint?: string;
  title?: string;
  subtitle?: string;
}

/** Every save of a region's forecast is a numbered version (V1 … Vn): list, compare any two, export, restore. */
export function VersionHistory({ region, products, currentSales, currentRegional, submitted, canRestore, restoreHint, title, subtitle }: Props) {
  const revisions = useRevisions(region);
  const list = revisions.data ?? [];
  const [from, setFrom] = useState<number | null>(null);
  const [to, setTo] = useState<number | null>(null);
  const [restoreTarget, setRestoreTarget] = useState<ForecastRevision | null>(null);
  const toast = useToast();

  // Default comparison: previous version → latest version (e.g. V5 → V6).
  const latest = list[0]?.revNo ?? null;
  const previous = list[1]?.revNo ?? null;
  useEffect(() => {
    setTo(latest);
    setFrom(previous);
  }, [region, latest, previous]);

  const restore = useApiMutation(
    ({ rev, comment }: { rev: number; comment: string }) => api.restoreRevision(region, rev, comment),
    (r, v) => `V${v.rev} restored as new version V${r.revision}`,
  );

  if (revisions.isLoading) return <Loading what="version history" />;
  if (revisions.error) return <QueryError error={revisions.error} />;

  return (
    <Panel
      title={title ?? `Version history — ${region}`}
      subtitle={subtitle ?? 'Every save (dashboard edit or Excel file) creates the next version. Saved versions never change.'}
    >
      {list.length === 0 ? (
        <Empty>No versions yet. Your first save creates a version here.</Empty>
      ) : (
        <>
          <div className="grid-wrap">
            <table className="grid mini version-table">
              <thead>
                <tr>
                  <th>Version</th>
                  <th>By</th>
                  <th>Source</th>
                  <th className="num">Changed</th>
                  <th className="num">Total</th>
                  <th>Comment</th>
                  <th>When</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {list.map((r) => (
                  <tr key={r.revNo} className={r.revNo === from || r.revNo === to ? 'row-changed' : undefined}>
                    <td className="strong nowrap">
                      {r.label}
                      {r.revNo === currentSales && <span className="chip chip-draft tag-gap">Sales current</span>}
                      {r.revNo === submitted && <span className="chip chip-submitted tag-gap">Submitted</span>}
                      {r.revNo === currentRegional && <span className="chip chip-approved tag-gap">Regional current</span>}
                    </td>
                    <td className="nowrap">
                      {r.createdBy}
                      <div className="muted small">{STAGE_LABEL[r.stage]}</div>
                    </td>
                    <td>
                      {SOURCE_LABEL[r.source] ?? r.source}
                      {r.fileName && <div className="muted small">{r.fileName}</div>}
                      {!r.applied && (
                        <div>
                          <span className="chip chip-draft" title="Uploaded while the forecast was locked; not in the working forecast">
                            History only
                          </span>
                        </div>
                      )}
                    </td>
                    <td className="num">{fmtQty(r.changed)}</td>
                    <td className="num strong">{fmtQty(r.total)}</td>
                    <td className="comment-cell">{r.comment}</td>
                    <td className="nowrap muted small">{fmtTime(r.createdAt)}</td>
                    <td className="nowrap">
                      <button className="btn btn-sm" onClick={() => api.exportRevision(region, r.revNo).catch(toast.error)} title={`Download ${r.label} as Excel`}>
                        ⇩
                      </button>
                      {canRestore && r.revNo !== latest && (
                        <button className="btn btn-sm" onClick={() => setRestoreTarget(r)} title={restoreHint}>
                          Restore
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {list.length > 1 && (
            <Compare region={region} products={products} versions={list} from={from} to={to} setFrom={setFrom} setTo={setTo} />
          )}
        </>
      )}
      <CommentModal
        open={!!restoreTarget}
        title={`Restore ${restoreTarget?.label ?? ''} — ${region}`}
        confirmLabel={`Restore as V${(latest ?? 0) + 1}`}
        onClose={() => setRestoreTarget(null)}
        onSubmit={(comment) => restore.mutateAsync({ rev: restoreTarget!.revNo, comment })}
      >
        <p>
          The quantities of <strong>{restoreTarget?.label}</strong> are copied into your working forecast and saved as a new version
          (<strong>V{(latest ?? 0) + 1}</strong>). Older versions stay unchanged.
        </p>
      </CommentModal>
    </Panel>
  );
}

function Compare({
  region,
  products,
  versions,
  from,
  to,
  setFrom,
  setTo,
}: {
  region: Region;
  products: Product[];
  versions: ForecastRevision[];
  from: number | null;
  to: number | null;
  setFrom: (n: number) => void;
  setTo: (n: number) => void;
}) {
  const a = useRevision(region, from);
  const b = useRevision(region, to);
  const [onlyChanged, setOnlyChanged] = useState(true);

  const rows = useMemo(() => {
    if (!a.data || !b.data) return [];
    return products.map((p) => {
      const x = a.data.lines[String(p.id)] ?? 0;
      const y = b.data.lines[String(p.id)] ?? 0;
      return { id: p.id, name: p.name, x, y, d: y - x };
    });
  }, [a.data, b.data, products]);
  const shown = onlyChanged ? rows.filter((r) => r.d !== 0) : rows;
  const totals = rows.reduce((t, r) => ({ x: t.x + r.x, y: t.y + r.y }), { x: 0, y: 0 });

  const picker = (value: number | null, onChange: (n: number) => void, label: string) => (
    <label className="field inline-field">
      <span>{label}</span>
      <select value={value ?? ''} onChange={(e) => onChange(Number(e.target.value))}>
        {versions.map((v) => (
          <option key={v.revNo} value={v.revNo}>
            {v.label} · {v.createdBy}
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <div className="compare">
      <div className="compare-head">
        <h3>Compare versions</h3>
        {picker(from, setFrom, 'From')}
        <span className="arrow" aria-hidden>
          →
        </span>
        {picker(to, setTo, 'To')}
        <label className="check">
          <input type="checkbox" checked={onlyChanged} onChange={(e) => setOnlyChanged(e.target.checked)} />
          Only changed products
        </label>
      </div>
      {a.isLoading || b.isLoading ? (
        <Loading what="versions" />
      ) : a.error || b.error ? (
        <QueryError error={a.error ?? b.error} />
      ) : (
        <div className="grid-wrap">
          <table className="grid mini">
            <thead>
              <tr>
                <th className="col-product">Product</th>
                <th className="num">V{from}</th>
                <th className="num">V{to}</th>
                <th className="num">Δ</th>
              </tr>
            </thead>
            <tbody>
              {shown.length === 0 ? (
                <tr>
                  <td colSpan={4} className="muted">
                    No differences between V{from} and V{to}.
                  </td>
                </tr>
              ) : (
                shown.map((r) => (
                  <tr key={r.id} className={r.d !== 0 ? 'row-changed' : undefined}>
                    <td className="col-product">{r.name}</td>
                    <td className="num muted">{fmtQty(r.x)}</td>
                    <td className="num strong">{fmtQty(r.y)}</td>
                    <td className={`num ${deltaClass(r.d)}`}>{fmtDelta(r.d)}</td>
                  </tr>
                ))
              )}
            </tbody>
            <tfoot>
              <tr>
                <th>Total</th>
                <td className="num">{fmtQty(totals.x)}</td>
                <td className="num">{fmtQty(totals.y)}</td>
                <td className={`num ${deltaClass(totals.y - totals.x)}`}>{fmtDelta(totals.y - totals.x)}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </div>
  );
}
