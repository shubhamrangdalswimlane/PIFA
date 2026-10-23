import { useDeferredValue, useState } from 'react';
import { useAudit, usePeriods } from '../api/hooks';
import { AUDIT_ENTITIES, REGIONS, ROLES, type AuditQuery, type Region } from '../api/types';
import { deltaClass, fmtDelta, fmtQty, fmtTime, ROLE_LABEL } from '../lib/format';
import { getPeriod, periodLabel } from '../period';
import { ExportButton } from './ExcelTools';
import { Loading, QueryError, StatusChip } from './ui';

interface AuditTableProps {
  /** Locks the region filter (Sales Manager history). */
  fixedRegion?: Region | null;
  /** Hide the role filter (e.g. own-region history). */
  hideRoleFilter?: boolean;
  showExport?: boolean;
  limit?: number;
}

/** Filterable audit trail (FR-H4, FR-A4, FR-S5) backed by GET /api/audit. */
export function AuditTable({ fixedRegion, hideRoleFilter, showExport = true, limit = 500 }: AuditTableProps) {
  const [role, setRole] = useState('');
  const [entity, setEntity] = useState('');
  const [region, setRegion] = useState('');
  const [q, setQ] = useState('');
  const [month, setMonth] = useState(''); // '' = selected month, 'all', or 'YYYY-MM'
  const periods = usePeriods();
  const selected = getPeriod();
  const deferredQ = useDeferredValue(q.trim());

  const query: AuditQuery = {
    role: role || undefined,
    entity: entity || undefined,
    region: (fixedRegion ?? region) || undefined,
    q: deferredQ || undefined,
    month: month || undefined,
    limit,
  };
  const audit = useAudit(query);
  const rows = audit.data ? [...audit.data].sort((a, b) => b.ts.localeCompare(a.ts)) : [];

  return (
    <div className="grid-block">
      <div className="grid-toolbar wrap">
        {!hideRoleFilter && (
          <select value={role} onChange={(e) => setRole(e.target.value)} aria-label="Role filter">
            <option value="">All roles</option>
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {ROLE_LABEL[r]}
              </option>
            ))}
          </select>
        )}
        <select value={month} onChange={(e) => setMonth(e.target.value)} aria-label="Month filter">
          <option value="">This month{selected ? ` (${periodLabel(selected)})` : ''}</option>
          <option value="all">All months</option>
          {(periods.data ?? [])
            .filter((p) => p.period !== selected)
            .map((p) => (
              <option key={p.period} value={p.period}>
                {p.label}
              </option>
            ))}
        </select>
        <select value={entity} onChange={(e) => setEntity(e.target.value)} aria-label="Entity filter">
          <option value="">All entities</option>
          {AUDIT_ENTITIES.map((x) => (
            <option key={x} value={x}>
              {x}
            </option>
          ))}
        </select>
        {fixedRegion ? (
          <span className="chip">{fixedRegion}</span>
        ) : (
          <select value={region} onChange={(e) => setRegion(e.target.value)} aria-label="Region filter">
            <option value="">All regions</option>
            {REGIONS.map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
        )}
        <input
          className="search"
          type="search"
          placeholder="Search user, product, comment…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          aria-label="Free-text filter"
        />
        <div className="spacer" />
        <span className="muted small">{audit.data ? `${rows.length} entries` : ''}</span>
        {showExport && <ExportButton kind="audit" label="⇩ Export audit" query={{ month: month || undefined }} />}
      </div>
      {audit.isLoading ? (
        <Loading what="audit" />
      ) : audit.error ? (
        <QueryError error={audit.error} />
      ) : (
        <div className="grid-wrap">
          <table className="grid audit">
            <thead>
              <tr>
                <th>When</th>
                <th>Month</th>
                <th>User</th>
                <th>Role</th>
                <th>Region</th>
                <th>Entity</th>
                <th>Ver.</th>
                <th>Product</th>
                <th className="num">Before</th>
                <th className="num">After</th>
                <th className="num">Δ</th>
                <th>Comment</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((e) => {
                const d = e.beforeQty !== null && e.afterQty !== null ? e.afterQty - e.beforeQty : null;
                return (
                  <tr key={e.id}>
                    <td className="nowrap">{fmtTime(e.ts)}</td>
                    <td className="nowrap">{e.periodLabel ? <span className="version-badge">{e.periodLabel}</span> : '—'}</td>
                    <td>{e.username}</td>
                    <td className="nowrap">{ROLE_LABEL[e.role as keyof typeof ROLE_LABEL] ?? e.role}</td>
                    <td>{e.region ?? '—'}</td>
                    <td>{e.entity}</td>
                    <td>{e.version ?? '—'}</td>
                    <td>{e.product ?? '—'}</td>
                    <td className="num">{fmtQty(e.beforeQty)}</td>
                    <td className="num">{fmtQty(e.afterQty)}</td>
                    <td className={`num ${deltaClass(d)}`}>{fmtDelta(d)}</td>
                    <td className="comment">{e.comment ?? ''}</td>
                    <td>{e.status ? <StatusChip status={e.status} /> : '—'}</td>
                  </tr>
                );
              })}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={13} className="empty">
                    No audit entries match.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
