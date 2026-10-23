import type { ReactNode } from 'react';
import type { Transfer } from '../api/types';
import { fmtQty, fmtTime } from '../lib/format';
import { Empty, Loading, QueryError, RegionTag, StatusChip } from './ui';

/**
 * Table of region-to-region unit transfers, newest first, with status, decision and optional per-row actions.
 * @param props.transfers - transfers to show
 * @param props.loading - shows a loading message
 * @param props.error - shows a load error
 * @param props.canUndo - decides whether a row gets an Undo button
 * @param props.onUndo - called when Undo is clicked
 * @param props.actions - extra per-row buttons (e.g. Head of Sales approve / reject)
 * @returns the rendered table, or a loading / error / empty message
 */
export function TransferList({
  transfers,
  loading,
  error,
  canUndo,
  onUndo,
  actions,
}: {
  transfers: Transfer[] | undefined;
  loading: boolean;
  error: unknown;
  canUndo?: (t: Transfer) => boolean;
  onUndo?: (t: Transfer) => void;
  /** Extra per-row buttons (e.g. Head of Sales approve / reject). */
  actions?: (t: Transfer) => ReactNode;
}) {
  if (loading) return <Loading what="transfers" />;
  if (error) return <QueryError error={error} />;
  const rows = [...(transfers ?? [])].sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  if (rows.length === 0) return <Empty>No transfers in this cycle.</Empty>;
  const hasActions = !!onUndo || !!actions;
  return (
    <div className="grid-wrap">
      <table className="grid">
        <thead>
          <tr>
            <th>When</th>
            <th>Who</th>
            <th>Product</th>
            <th>From → To</th>
            <th className="num">Units</th>
            <th>Comment</th>
            <th>Status</th>
            {hasActions && <th />}
          </tr>
        </thead>
        <tbody>
          {rows.map((t) => (
            <tr key={t.id} className={t.status === 'undone' || t.status === 'rejected' ? 'row-muted' : undefined}>
              <td className="nowrap">{fmtTime(t.createdAt)}</td>
              <td>
                {t.requestedBy} <span className="muted small">({t.requestedRegion})</span>
              </td>
              <td>{t.product}</td>
              <td className="nowrap">
                <RegionTag region={t.fromRegion} /> → <RegionTag region={t.toRegion} />
              </td>
              <td className="num">{fmtQty(t.qty)}</td>
              <td className="comment">{t.comment}</td>
              <td>
                <StatusChip status={t.status} />
                {t.decidedBy && (
                  <div className="muted small" title={t.decidedAt ? fmtTime(t.decidedAt) : undefined}>
                    by {t.decidedBy}
                    {t.decisionComment ? `: ${t.decisionComment}` : ''}
                  </div>
                )}
              </td>
              {hasActions && (
                <td className="nowrap">
                  {onUndo && canUndo?.(t) && (
                    <button className="btn btn-small" onClick={() => onUndo(t)}>
                      Undo
                    </button>
                  )}
                  {actions?.(t)}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
