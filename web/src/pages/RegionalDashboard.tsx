import { useMemo, useState } from 'react';
import { api } from '../api/client';
import { useAllocation, useApiMutation, useCycle, useForecast, useInventory, useNextRevision, useProducts, useTransfers } from '../api/hooks';
import { REGIONS, type Cycle, type ForecastResponse, type Product, type Region, type Transfer } from '../api/types';
import { VersionHistory } from '../components/VersionHistory';
import { useSession } from '../auth/session';
import { AuditTable } from '../components/AuditTable';
import { TransferList } from '../components/TransferList';
import type { CellChange } from '../components/EditableGrid';
import { ExportButton } from '../components/ExcelTools';
import { allocationVersionMap, AllocationGrid, ForecastRegionsGrid, type AllocVersion, type FcVersion } from '../components/Matrices';
import { CommentModal } from '../components/Modal';
import { Banner, Empty, Loading, Panel, QueryError, RegionTag, StatusChip, Tabs, VersionSwitch } from '../components/ui';
import { deltaClass, fmtDelta, fmtQty, fmtTime } from '../lib/format';

type Tab = 'forecast' | 'allocation' | 'history';

/**
 * Regional Manager dashboard for their own region: review and revise the forecast (approve / reject the
 * Sales Manager's submission), confirm the allocation and shift units between regions, and see own change history.
 * @returns the rendered dashboard page, or a banner when the account has no region
 */
export default function RegionalDashboard() {
  const { region } = useSession();
  const [tab, setTab] = useState<Tab>('forecast');
  if (!region) return <Banner kind="danger">Your account has no region claim. Ask the administrator to set it.</Banner>;
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Regional review</h1>
          <p className="muted">
            Your region: <RegionTag region={region} own />
          </p>
        </div>
      </div>
      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        tabs={[
          { value: 'forecast', label: 'Forecast' },
          { value: 'allocation', label: 'Allocation & unit shifts' },
          { value: 'history', label: 'History' },
        ]}
      />
      {tab === 'forecast' && <ForecastTab region={region} />}
      {tab === 'allocation' && <AllocationTab region={region} />}
      {tab === 'history' && (
        <Panel title="My change history" subtitle="Only the changes you made.">
          <AuditTable hideRoleFilter />
        </Panel>
      )}
    </div>
  );
}

/**
 * One card per region with its Sales / Regional forecast statuses and the version numbers they are on.
 * @param props.cycle - workflow state of the selected month
 * @param props.own - the user's region (highlighted)
 * @param props.revs - per-region forecast statuses with version numbers
 * @returns the rendered row of region cards
 */
function RegionStatusRow({ cycle, own, revs }: { cycle: Cycle | undefined; own: Region; revs?: ForecastResponse['status'] }) {
  return (
    <div className="region-status">
      {REGIONS.map((r) => (
        <div key={r} className={`region-card${r === own ? ' own' : ''}`}>
          <RegionTag region={r} own={r === own} />
          <div className="small">
            Sales <StatusChip status={cycle?.forecast[r]?.v1} /> Regional <StatusChip status={cycle?.forecast[r]?.v2} />
          </div>
          {(revs?.[r]?.v1SubmittedRev || revs?.[r]?.v2Rev) && (
            <div className="small muted">
              Sales final V{revs?.[r]?.v1SubmittedRev ?? '—'} · Regional V{revs?.[r]?.v2Rev ?? '—'}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

/**
 * Forecast review at stage 2: all regions side by side (Sales final, or Regional vs Sales); the own region's
 * Regional column is editable (each save is a new version), with approve / reject buttons and the own version history.
 * @param props.region - the Regional Manager's region
 * @returns the rendered forecast tab
 */
function ForecastTab({ region }: { region: Region }) {
  const cycle = useCycle();
  const forecast = useForecast();
  const [version, setVersion] = useState<FcVersion>('v2');
  const [approveOpen, setApproveOpen] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);

  const status = forecast.data?.status[region] ?? cycle.data?.forecast[region];
  const stage = cycle.data?.stage ?? 0;
  // Editable all through stage 2 (also after approving; an edit then needs a new approval).
  const canEdit = stage === 2 && status?.v1 === 'submitted' && (status?.v2 === 'draft' || status?.v2 === 'approved');
  const canReview = canEdit && status?.v2 === 'draft';
  const salesFinal = forecast.data?.status[region]?.v1SubmittedRev ?? forecast.data?.status[region]?.v1Rev ?? null;
  const regionalRev = forecast.data?.status[region]?.v2Rev ?? null;
  const nextRev = useNextRevision(region);

  /**
   * Saves edits to the region's Regional Manager revision (version 2); the toast names the new version or says nothing changed.
   */
  const save = useApiMutation(
    ({ changes, comment }: { changes: CellChange[]; comment: string }) =>
      api.putForecast(
        region,
        2,
        changes.map((c) => ({ productId: c.productId, qty: c.qty })),
        comment,
      ),
    (r) =>
      r.revision
        ? `${region}: saved as version V${r.revision} (${r.updated} line${r.updated === 1 ? '' : 's'} changed)`
        : 'No changes — no new version created',
  );
  /**
   * Approves the region's forecast (optional comment).
   */
  const approve = useApiMutation((c: string) => api.approveForecast(region, c || undefined), `${region} forecast approved`);
  /**
   * Rejects the region's forecast back to the Sales Manager (comment required).
   */
  const reject = useApiMutation((c: string) => api.rejectForecast(region, c), `${region} forecast rejected and returned to the Sales Manager`);

  if (forecast.isLoading) return <Loading what="forecast" />;
  if (forecast.error) return <QueryError error={forecast.error} />;
  const fc = forecast.data!;
  const products = fc.products;

  return (
    <>
      <RegionStatusRow cycle={cycle.data} own={region} revs={forecast.data?.status} />
      {stage === 2 && status?.v1 !== 'submitted' && (
        <Banner kind="info">Waiting for the {region} Sales Manager to submit their final forecast version.</Banner>
      )}
      {canEdit && (
        <Banner kind={status?.v2 === 'approved' ? 'success' : 'info'}>
          {status?.v2 === 'approved' ? (
            <>
              <strong>{region} is approved.</strong> You can still edit it while the other regions are reviewed; an edit
              withdraws the approval so you approve again.{' '}
            </>
          ) : null}
          You are working from the {region} Sales Manager's latest version <strong>V{salesFinal}</strong>
          {regionalRev && regionalRev !== salesFinal ? (
            <>
              ; your latest revision is <strong>V{regionalRev}</strong>
            </>
          ) : null}
          . Each save creates the next version (V{nextRev}). If the Sales Manager saves a new version, it replaces your revision here
          (yours stays in the version history).
        </Banner>
      )}
      <Panel
        title="Forecast — all regions"
        subtitle={
          canEdit
            ? `Edit the ${region} Regional column with a reason per change${canReview ? ', then approve or reject' : ''}.`
            : 'Read-only at this stage.'
        }
        actions={
          <>
            <VersionSwitch<FcVersion>
              value={version}
              onChange={setVersion}
              options={[
                { value: 'v1', label: 'Sales final' },
                { value: 'v2', label: 'Regional vs Sales' },
              ]}
            />
            {canReview && (
              <>
                <button className="btn btn-danger" onClick={() => setRejectOpen(true)}>
                  Reject {region}
                </button>
                <button className="btn btn-primary" onClick={() => setApproveOpen(true)}>
                  Approve {region}
                </button>
              </>
            )}
          </>
        }
      >
        <ForecastRegionsGrid
          forecast={fc}
          version={version}
          ownRegion={region}
          editableRegion={canEdit && version === 'v2' ? region : null}
          onSave={canEdit && version === 'v2' ? (changes, comment) => save.mutateAsync({ changes, comment }) : undefined}
          toolbar={
            <>
              <ExportButton kind="forecast" version={version === 'v1' ? '1' : '2'} />
            </>
          }
        />
      </Panel>
      <VersionHistory
        region={region}
        products={products}
        title={`My versions — ${region}`}
        subtitle="Only the versions you saved (your regional revisions). Saved versions never change."
        currentRegional={fc.status[region]?.v2 ? (fc.status[region]?.v2Rev ?? null) : null}
        canRestore={canEdit}
        restoreHint="Copy this version into your regional revision as a new version"
      />
      <CommentModal
        open={approveOpen}
        title={`Approve ${region} forecast${regionalRev ? ` (V${regionalRev})` : ''}`}
        confirmLabel="Approve"
        required={false}
        onClose={() => setApproveOpen(false)}
        onSubmit={(c) => approve.mutateAsync(c)}
      >
        <p>Planning starts when all four regions are approved.</p>
      </CommentModal>
      <CommentModal
        open={rejectOpen}
        title={`Reject ${region} forecast`}
        confirmLabel="Reject"
        danger
        placeholder="Explain what the Sales Manager should change"
        onClose={() => setRejectOpen(false)}
        onSubmit={(c) => reject.mutateAsync(c)}
      >
        <p>The forecast goes back to the {region} Sales Manager to revise and resubmit (R-FC-03: comment required).</p>
      </CommentModal>
    </>
  );
}

/**
 * Allocation at stage 4: per-region confirmation status, unit transfer form, allocation V1 / V2 / Final with
 * balance, transfer list (undo own pending transfers) and the "Confirm region" action.
 * @param props.region - the Regional Manager's region
 * @returns the rendered allocation tab
 */
function AllocationTab({ region }: { region: Region }) {
  const { username } = useSession();
  const cycle = useCycle();
  const products = useProducts();
  const allocation = useAllocation();
  const inventory = useInventory();
  const transfers = useTransfers();
  const [version, setVersion] = useState<AllocVersion | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [undoTarget, setUndoTarget] = useState<Transfer | null>(null);

  const stage = cycle.data?.stage ?? 0;
  const confirmed = cycle.data?.confirmations[region];
  /**
   * Confirms the region's allocation (optional comment).
   */
  const confirm = useApiMutation((c: string) => api.confirmAllocation(c || undefined), `${region} allocation confirmed`);
  /**
   * Undoes one of the user's pending transfers (comment required).
   */
  const undo = useApiMutation(({ id, comment }: { id: number; comment: string }) => api.undoTransfer(id, comment), 'Transfer undone');

  const a = allocation.data;
  const v = version ?? (a?.final ? 'final' : a?.v2 ? 'v2' : 'v1');

  if (allocation.isLoading || products.isLoading) return <Loading what="allocation" />;
  if (allocation.error) return <QueryError error={allocation.error} />;
  if (products.error) return <QueryError error={products.error} />;

  const transferBox = (
    <TransferBox
      products={products.data ?? []}
      v2={a?.v2 ?? null}
      ownRegion={region}
      disabledReason={
        stage === 4
          ? null
          : stage < 4
            ? `Shifting units opens once the Planner approves allocation V1 (stage 4). The cycle is at stage ${stage}.`
            : 'Regional changes are closed: the allocation is with the Head of Sales or already published.'
      }
    />
  );

  if (!a?.v1 && !a?.v2)
    return (
      <>
        {transferBox}
        <Empty>No allocation yet. The Planner publishes allocation V1 at the end of stage 3.</Empty>
      </>
    );

  return (
    <>
      <div className="region-status">
        {REGIONS.map((r) => {
          const c = cycle.data?.confirmations[r];
          return (
            <div key={r} className={`region-card${r === region ? ' own' : ''}`}>
              <RegionTag region={r} own={r === region} />
              <div className="small">{c ? <>Confirmed by {c.by} · {fmtTime(c.at)}</> : <span className="muted">Not confirmed</span>}</div>
            </div>
          );
        })}
      </div>

      {transferBox}

      <Panel
        title="Allocation"
        subtitle="Balance = inventory − allocated."
        actions={
          <>
            <VersionSwitch<AllocVersion>
              value={v}
              onChange={setVersion}
              options={[
                { value: 'v1', label: 'V1', disabled: !a.v1 },
                { value: 'v2', label: 'V2', disabled: !a.v2 },
                { value: 'final', label: 'Final', disabled: !a.final },
              ]}
            />
            <ExportButton kind="allocation" version={v === 'v1' ? '1' : v === 'v2' ? '2' : 'final'} />
            {stage === 4 && !confirmed && (
              <button className="btn btn-primary" onClick={() => setConfirmOpen(true)}>
                Confirm {region}
              </button>
            )}
            {stage === 4 && confirmed && <span className="chip chip-approved">{region} confirmed</span>}
          </>
        }
      >
        {!allocationVersionMap(a, v) ? (
          <Empty>This version does not exist yet.</Empty>
        ) : (
          <AllocationGrid products={products.data ?? []} allocation={a} version={v} inventory={inventory.data?.lines ?? null} ownRegion={region} />
        )}
      </Panel>

      <Panel title="Transfers" subtitle="Transfers apply to allocation V2 immediately and clear all confirmations.">
        <TransferList
          transfers={transfers.data}
          loading={transfers.isLoading}
          error={transfers.error}
          canUndo={(t) => stage === 4 && t.status === 'pending' && t.requestedBy === username}
          onUndo={setUndoTarget}
        />
      </Panel>

      <CommentModal
        open={confirmOpen}
        title={`Confirm ${region} allocation`}
        confirmLabel="Confirm"
        required={false}
        onClose={() => setConfirmOpen(false)}
        onSubmit={(c) => confirm.mutateAsync(c)}
      >
        <p>The cycle goes to the Head of Sales when all four regions confirm. A new transfer clears all confirmations.</p>
      </CommentModal>
      <CommentModal
        open={!!undoTarget}
        title="Undo transfer"
        confirmLabel="Undo transfer"
        danger
        onClose={() => setUndoTarget(null)}
        onSubmit={(c) => undo.mutateAsync({ id: undoTarget!.id, comment: c })}
      >
        {undoTarget && (
          <p>
            {undoTarget.product}: {undoTarget.fromRegion} → {undoTarget.toRegion}, {undoTarget.qty} units will be reversed.
          </p>
        )}
      </CommentModal>
    </>
  );
}

/**
 * Form to shift units of one product from one region to another in Allocation V2 (R-XFER-01), with
 * validation (different regions, whole units > 0, not more than the source holds, comment required)
 * and a live before/after preview per region; the product total stays the same.
 * @param props.products - products to choose from
 * @param props.v2 - current Allocation V2 matrix (region → productId → qty), or null if none
 * @param props.ownRegion - the user's region (default source)
 * @param props.disabledReason - when set, the form is read-only and this explanation is shown
 * @returns the rendered transfer panel
 */
function TransferBox({
  products,
  v2,
  ownRegion,
  disabledReason,
}: {
  products: Product[];
  v2: Partial<Record<Region, Record<string, number>>> | null;
  ownRegion: Region;
  /** When set, the box is shown read-only with this explanation. */
  disabledReason?: string | null;
}) {
  const [productId, setProductId] = useState<number | ''>('');
  // Default reads like the PRD example: from your region to the next one (e.g. North → East).
  const [from, setFrom] = useState<Region>(ownRegion);
  const [to, setTo] = useState<Region>(REGIONS[(REGIONS.indexOf(ownRegion) + 1) % REGIONS.length]);
  const [units, setUnits] = useState('');
  const [comment, setComment] = useState('');
  const [productFilter, setProductFilter] = useState('');

  /**
   * Creates the transfer; it is applied to Allocation V2 immediately.
   */
  const create = useApiMutation(api.createTransfer, (t) => `Transfer ${t.fromRegion} → ${t.toRegion} (${t.qty}) applied to V2`);

  const filtered = useMemo(() => {
    const f = productFilter.trim().toLowerCase();
    return f ? products.filter((p) => p.name.toLowerCase().includes(f)) : products;
  }, [products, productFilter]);

  /**
   * @param r - region
   * @returns the chosen product's current V2 quantity in that region (0 when no product is chosen)
   */
  const qtyOf = (r: Region) => (productId === '' ? 0 : (v2?.[r]?.[String(productId)] ?? 0));
  const n = /^\d+$/.test(units.trim()) ? Number(units) : NaN;
  const source = qtyOf(from);

  const problems: string[] = [];
  if (productId === '') problems.push('Choose a product.');
  if (from === to) problems.push('Choose two different regions.');
  if (!Number.isInteger(n) || n <= 0) problems.push('Units must be a whole number above 0.');
  else if (productId !== '' && n > source) problems.push(`Units cannot exceed ${from}'s allocation (${source}).`);
  if (!comment.trim()) problems.push('A comment is required.');
  if (!v2) problems.push('Allocation V2 is not available.');

  /**
   * Quantity a region would hold after the transfer, for the preview.
   * @param r - region
   * @returns the quantity after the transfer (unchanged when the entry is not valid)
   */
  const after = (r: Region) => {
    const b = qtyOf(r);
    if (!Number.isInteger(n) || n <= 0 || from === to) return b;
    return r === from ? b - n : r === to ? b + n : b;
  };
  const total = REGIONS.reduce((s, r) => s + qtyOf(r), 0);

  /**
   * Creates the transfer when the form is valid and clears units and comment on success (errors are shown as a toast).
   * @returns a Promise that settles when the request is finished
   */
  const submit = async () => {
    if (problems.length || productId === '') return;
    try {
      await create.mutateAsync({ productId, fromRegion: from, toRegion: to, qty: n, comment: comment.trim() });
      setUnits('');
      setComment('');
    } catch {
      /* toast shown */
    }
  };

  return (
    <Panel
      title="Shift units between regions"
      subtitle="Decrease one region and increase another for a product in the Planner's allocation, e.g. North → East, 15 units (R-XFER-01). The product total stays the same."
    >
      {disabledReason && <Banner kind="info">{disabledReason}</Banner>}
      <fieldset className="transfer-fieldset" disabled={!!disabledReason}>
      <div className="transfer-box">
        <div className="transfer-form">
          <label className="field">
            <span>Product</span>
            <input type="search" placeholder="Filter products…" value={productFilter} onChange={(e) => setProductFilter(e.target.value)} />
            <select value={productId} onChange={(e) => setProductId(e.target.value ? Number(e.target.value) : '')} size={1}>
              <option value="">— choose product ({filtered.length}) —</option>
              {filtered.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
          <div className="field-row">
            <label className="field">
              <span>Decrease (from)</span>
              <select value={from} onChange={(e) => setFrom(e.target.value as Region)}>
                {REGIONS.map((r) => (
                  <option key={r}>{r}</option>
                ))}
              </select>
            </label>
            <span className="arrow" aria-hidden>
              →
            </span>
            <label className="field">
              <span>Increase (to)</span>
              <select value={to} onChange={(e) => setTo(e.target.value as Region)}>
                {REGIONS.map((r) => (
                  <option key={r}>{r}</option>
                ))}
              </select>
            </label>
            <label className="field narrow">
              <span>Units</span>
              <input inputMode="numeric" value={units} onChange={(e) => setUnits(e.target.value)} placeholder="15" />
            </label>
          </div>
          <label className="field">
            <span>
              Comment <span className="req">(required)</span>
            </span>
            <textarea rows={2} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Reason for the transfer" />
          </label>
          {problems.length > 0 && (productId !== '' || units || comment) && (
            <ul className="problems inline">
              {problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          )}
          <div>
            <button className="btn btn-primary" disabled={problems.length > 0 || create.isPending} onClick={submit}>
              {create.isPending ? 'Applying…' : 'Apply transfer'}
            </button>
          </div>
        </div>
        <div className="transfer-preview">
          <h3>Live preview{productId !== '' && <> — {products.find((p) => p.id === productId)?.name}</>}</h3>
          <table className="grid mini">
            <thead>
              <tr>
                <th>Region</th>
                <th className="num">Before</th>
                <th className="num">After</th>
                <th className="num">Δ</th>
              </tr>
            </thead>
            <tbody>
              {REGIONS.map((r) => {
                const b = qtyOf(r);
                const af = after(r);
                return (
                  <tr key={r} className={r === from || r === to ? 'row-changed' : undefined}>
                    <td>
                      <RegionTag region={r} own={r === ownRegion} />
                    </td>
                    <td className="num">{fmtQty(b)}</td>
                    <td className={`num strong${af < 0 ? ' delta-neg' : ''}`}>{fmtQty(af)}</td>
                    <td className={`num ${deltaClass(af - b)}`}>{fmtDelta(af - b)}</td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr>
                <th>Total</th>
                <td className="num">{fmtQty(total)}</td>
                <td className="num">{fmtQty(REGIONS.reduce((s, r) => s + after(r), 0))}</td>
                <td className="num delta-zero">0</td>
              </tr>
            </tfoot>
          </table>
          <p className="muted small">Per-model total is preserved.</p>
        </div>
      </div>
      </fieldset>
    </Panel>
  );
}

