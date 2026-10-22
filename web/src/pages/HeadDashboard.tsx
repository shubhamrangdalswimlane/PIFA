import { useState } from 'react';
import { api } from '../api/client';
import { useApiMutation, useCycle, useSummary, useTransfers } from '../api/hooks';
import { REGIONS, type Summary, type Transfer } from '../api/types';
import { AuditTable } from '../components/AuditTable';
import { DataViews } from '../components/DataViews';
import { CommentModal } from '../components/Modal';
import { TransferList } from '../components/TransferList';
import { Banner, Loading, Panel, QueryError, RegionTag, Tabs } from '../components/ui';
import { fmtQty, REGION_CLASS } from '../lib/format';

type Tab = 'overview' | 'data' | 'transfers' | 'audit';

export default function HeadDashboard() {
  const cycle = useCycle();
  const summary = useSummary();
  const transfers = useTransfers();
  const [tab, setTab] = useState<Tab>('overview');
  const [approveOpen, setApproveOpen] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  const stage = cycle.data?.stage ?? 0;

  const [decision, setDecision] = useState<{ t: Transfer; kind: 'approve' | 'reject' } | null>(null);
  const [approveAllOpen, setApproveAllOpen] = useState(false);

  const approve = useApiMutation((c: string) => api.approveAllocation(c || undefined), 'Allocation approved and published');
  const reject = useApiMutation((c: string) => api.rejectAllocation(c), 'Allocation rejected — returned to Regional change');
  const decide = useApiMutation(
    ({ t, kind, comment }: { t: Transfer; kind: 'approve' | 'reject'; comment: string }) =>
      kind === 'approve' ? api.approveTransfer(t.id, comment || undefined) : api.rejectTransfer(t.id, comment),
    (t) =>
      t.status === 'rejected'
        ? `Transfer rejected: ${t.qty} ${t.product} moved back ${t.toRegion} → ${t.fromRegion}`
        : `Transfer approved: ${t.fromRegion} → ${t.toRegion}, ${t.qty} ${t.product}`,
  );
  const approveAll = useApiMutation(
    (c: string) => api.approveAllTransfers(c || undefined),
    (r) => `${r.approved} transfer${r.approved === 1 ? '' : 's'} approved`,
  );
  const pending = (transfers.data ?? []).filter((t) => t.status === 'pending');
  const canDecide = stage === 5;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Head of Sales</h1>
          <p className="muted">Read-only view of all regions; approve or reject the final allocation.</p>
        </div>
        <div className="page-actions">
          {stage === 5 && (
            <>
              <button className="btn btn-danger" onClick={() => setRejectOpen(true)}>
                Reject
              </button>
              <button className="btn btn-primary" onClick={() => setApproveOpen(true)}>
                Approve &amp; publish
              </button>
            </>
          )}
        </div>
      </div>
      {stage > 0 && stage < 5 && (
        <Banner kind="info">
          <strong>Approve &amp; publish</strong> and <strong>Reject</strong> appear here at stage 5 (Final approval), once all four
          Regional Managers have confirmed the allocation. Waiting for: <strong>{cycle.data?.nextActor}</strong>.
        </Banner>
      )}
      {stage === 5 && (
        <Banner kind="warn">
          All regions confirmed. In the <strong>Transfers</strong> tab, approve or reject each transfer (or approve all), then{' '}
          <strong>Approve &amp; publish</strong> the allocation, or <strong>Reject</strong> it back to the Regional Managers.
        </Banner>
      )}
      {stage === 6 && <Banner kind="success">The allocation for this cycle is published.</Banner>}

      {summary.isLoading ? <Loading what="summary" /> : summary.error ? <QueryError error={summary.error} /> : <Kpis s={summary.data!} />}

      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        tabs={[
          { value: 'overview', label: 'Region comparison' },
          { value: 'data', label: 'Forecast & allocation' },
          { value: 'transfers', label: `Transfers${summary.data ? ` (${summary.data.transfersPending} pending)` : ''}` },
          { value: 'audit', label: 'Audit' },
        ]}
      />
      {tab === 'overview' && summary.data && (
        <Panel title="Region comparison" subtitle="Forecast V1 / V2 vs allocation (final if published, else V2, else V1).">
          <RegionBars s={summary.data} />
        </Panel>
      )}
      {tab === 'data' && <DataViews />}
      {tab === 'transfers' && (
        <Panel
          title="Transfers to review"
          subtitle={
            canDecide
              ? 'Approve or reject each transfer, or approve all pending at once. A rejected transfer moves its units back. Approve & publish approves any transfers still pending.'
              : 'Decisions on transfers open at stage 5 (Final approval).'
          }
          actions={
            canDecide && pending.length > 0 ? (
              <button className="btn btn-primary" onClick={() => setApproveAllOpen(true)}>
                Approve all pending ({pending.length})
              </button>
            ) : undefined
          }
        >
          <TransferList
            transfers={transfers.data}
            loading={transfers.isLoading}
            error={transfers.error}
            actions={
              canDecide
                ? (t) =>
                    t.status === 'pending' && (
                      <>
                        <button className="btn btn-small" onClick={() => setDecision({ t, kind: 'approve' })}>
                          Approve
                        </button>{' '}
                        <button className="btn btn-small btn-danger" onClick={() => setDecision({ t, kind: 'reject' })}>
                          Reject
                        </button>
                      </>
                    )
                : undefined
            }
          />
        </Panel>
      )}
      {tab === 'audit' && (
        <Panel title="Audit trail">
          <AuditTable />
        </Panel>
      )}

      <CommentModal
        open={approveOpen}
        title="Approve and publish allocation"
        confirmLabel="Approve & publish"
        required={false}
        onClose={() => setApproveOpen(false)}
        onSubmit={(c) => approve.mutateAsync(c)}
      >
        <p>
          Publishes allocation V2 as final and writes the export to SFTP /outbound.
          {pending.length > 0 && (
            <>
              {' '}
              The <strong>{pending.length}</strong> transfer{pending.length === 1 ? '' : 's'} still pending will be approved with it.
            </>
          )}
        </p>
      </CommentModal>
      <CommentModal
        open={!!decision}
        title={decision?.kind === 'reject' ? 'Reject transfer' : 'Approve transfer'}
        confirmLabel={decision?.kind === 'reject' ? 'Reject transfer' : 'Approve transfer'}
        danger={decision?.kind === 'reject'}
        required={decision?.kind === 'reject'}
        placeholder={decision?.kind === 'reject' ? 'Why is this transfer rejected?' : 'Optional note'}
        onClose={() => setDecision(null)}
        onSubmit={(comment) => decide.mutateAsync({ t: decision!.t, kind: decision!.kind, comment })}
      >
        {decision && (
          <p>
            {decision.t.product}: <strong>{decision.t.fromRegion} → {decision.t.toRegion}</strong>, {decision.t.qty} units (by{' '}
            {decision.t.requestedBy}).
            {decision.kind === 'reject' && <> The units move back to {decision.t.fromRegion} in allocation V2.</>}
          </p>
        )}
      </CommentModal>
      <CommentModal
        open={approveAllOpen}
        title="Approve all pending transfers"
        confirmLabel={`Approve ${pending.length}`}
        required={false}
        onClose={() => setApproveAllOpen(false)}
        onSubmit={(c) => approveAll.mutateAsync(c)}
      >
        <p>
          Approves the {pending.length} pending transfer{pending.length === 1 ? '' : 's'}. The allocation is published only when you
          click <strong>Approve &amp; publish</strong>.
        </p>
      </CommentModal>
      <CommentModal
        open={rejectOpen}
        title="Reject allocation"
        confirmLabel="Reject"
        danger
        onClose={() => setRejectOpen(false)}
        onSubmit={(c) => reject.mutateAsync(c)}
      >
        <p>Returns the cycle to stage 4 (Regional change) and clears all regional confirmations (R-APPR-01).</p>
      </CommentModal>
    </div>
  );
}

function Kpis({ s }: { s: Summary }) {
  const cards = [
    { label: 'Forecast V1', value: s.forecastV1 },
    { label: 'Forecast V2', value: s.forecastV2, delta: s.forecastV2 - s.forecastV1 },
    { label: 'Inventory', value: s.inventory },
    { label: 'Allocated', value: s.allocated, sub: s.inventory ? `${Math.round((s.allocated / s.inventory) * 100)}% of inventory` : undefined },
    { label: 'Transfers pending', value: s.transfersPending },
  ];
  return (
    <div className="kpis">
      {cards.map((c) => (
        <div key={c.label} className="kpi">
          <div className="kpi-label">{c.label}</div>
          <div className="kpi-value">{fmtQty(c.value)}</div>
          {c.delta !== undefined && (
            <div className={`kpi-sub ${c.delta > 0 ? 'delta-pos' : c.delta < 0 ? 'delta-neg' : ''}`}>
              {c.delta > 0 ? '+' : ''}
              {fmtQty(c.delta)} vs V1
            </div>
          )}
          {c.sub && <div className="kpi-sub muted">{c.sub}</div>}
        </div>
      ))}
    </div>
  );
}

function RegionBars({ s }: { s: Summary }) {
  const rows = REGIONS.map((r) => {
    const b = s.byRegion[r];
    const alloc = b ? (b.final ?? (b.allocationV2 || b.allocationV1)) : 0;
    return { r, v1: b?.forecastV1 ?? 0, v2: b?.forecastV2 ?? 0, alloc };
  });
  const max = Math.max(1, ...rows.flatMap((x) => [x.v1, x.v2, x.alloc]));
  const series = [
    { key: 'v1' as const, label: 'Forecast V1', cls: 'bar-v1' },
    { key: 'v2' as const, label: 'Forecast V2', cls: 'bar-v2' },
    { key: 'alloc' as const, label: 'Allocation', cls: 'bar-alloc' },
  ];
  return (
    <div className="bars">
      <div className="bars-legend">
        {series.map((x) => (
          <span key={x.key}>
            <span className={`swatch ${x.cls}`} /> {x.label}
          </span>
        ))}
      </div>
      {rows.map((row) => (
        <div key={row.r} className={`bar-group ${REGION_CLASS[row.r]}`}>
          <div className="bar-region">
            <RegionTag region={row.r} />
          </div>
          <div className="bar-stack">
            {series.map((x) => (
              <div key={x.key} className="bar-line" title={`${row.r} ${x.label}: ${fmtQty(row[x.key])}`}>
                <div className={`bar ${x.cls}`} style={{ width: `${(row[x.key] / max) * 100}%` }} />
                <span className="bar-value">{fmtQty(row[x.key])}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
