import { useState } from 'react';
import { api } from '../api/client';
import { useApiMutation, useCycle, useSummary, useTransfers } from '../api/hooks';
import type { Summary, Transfer } from '../api/types';
import { AllocationLogic } from '../components/AllocationLogic';
import { AuditTable } from '../components/AuditTable';
import { DataViews } from '../components/DataViews';
import { CommentModal } from '../components/Modal';
import { TransferList } from '../components/TransferList';
import { Banner, Loading, Panel, QueryError, Tabs } from '../components/ui';
import { fmtQty } from '../lib/format';

type Tab = 'data' | 'transfers' | 'logic' | 'audit';

/**
 * Head of Sales dashboard: KPI cards, region comparison chart, read-only forecast / allocation data,
 * transfer review (approve / reject each or all pending) and the audit trail. At stage 5 the Head
 * approves and publishes the allocation as Final, or rejects it back to stage 4.
 * @returns the rendered dashboard page
 */
export default function HeadDashboard() {
  const cycle = useCycle();
  const summary = useSummary();
  const transfers = useTransfers();
  const [tab, setTab] = useState<Tab>('data');
  const [approveOpen, setApproveOpen] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  const stage = cycle.data?.stage ?? 0;

  const [decision, setDecision] = useState<{ t: Transfer; kind: 'approve' | 'reject' } | null>(null);
  const [approveAllOpen, setApproveAllOpen] = useState(false);

  /**
   * Approves and publishes the allocation (optional comment).
   */
  const approve = useApiMutation((c: string) => api.approveAllocation(c || undefined), 'Allocation approved and published');
  /**
   * Rejects the allocation back to Regional change (comment required).
   */
  const reject = useApiMutation((c: string) => api.rejectAllocation(c), 'Allocation rejected — returned to Regional change');
  /**
   * Approves or rejects one transfer; a rejected transfer's units move back.
   */
  const decide = useApiMutation(
    ({ t, kind, comment }: { t: Transfer; kind: 'approve' | 'reject'; comment: string }) =>
      kind === 'approve' ? api.approveTransfer(t.id, comment || undefined) : api.rejectTransfer(t.id, comment),
    (t) =>
      t.status === 'rejected'
        ? `Transfer rejected: ${t.qty} ${t.product} moved back ${t.toRegion} → ${t.fromRegion}`
        : `Transfer approved: ${t.fromRegion} → ${t.toRegion}, ${t.qty} ${t.product}`,
  );
  /**
   * Approves all pending transfers (optional comment).
   */
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
          { value: 'data', label: 'Forecast & allocation' },
          { value: 'transfers', label: `Transfers${summary.data ? ` (${summary.data.transfersPending} pending)` : ''}` },
          { value: 'logic', label: 'Allocation logic' },
          { value: 'audit', label: 'Audit' },
        ]}
      />
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
      {tab === 'logic' && <AllocationLogic canEdit />}
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

/**
 * KPI cards: forecast V1 and V2 (with change vs V1), inventory, allocated (with share of inventory) and pending transfers.
 * @param props.s - summary totals
 * @returns the rendered KPI row
 */
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
