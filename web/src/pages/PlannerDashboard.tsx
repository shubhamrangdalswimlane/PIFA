import { useCallback, useMemo, useState } from 'react';
import { api } from '../api/client';
import { useAllocation, useApiMutation, useCycle, useFiles, useForecast, useInventory, useProducts } from '../api/hooks';
import type { ForecastResponse, Product, QtyMap, Violation } from '../api/types';
import { AuditTable } from '../components/AuditTable';
import { EditableGrid, type CellChange, type Eff, type GridColumn, type RowTone } from '../components/EditableGrid';
import { ExportButton, UploadButton } from '../components/ExcelTools';
import { allocationVersionMap, AllocationGrid, type AllocVersion } from '../components/Matrices';
import { CommentModal, Modal } from '../components/Modal';
import { ProblemList } from '../components/Toast';
import { Banner, Empty, Loading, Panel, QueryError, StatusChip, Tabs, VersionSwitch } from '../components/ui';
import { currentFromMatrix, currentFromQty } from '../lib/excel';
import { fmtTime } from '../lib/format';
import { ApiError } from '../api/client';
import { REGIONS, type Region } from '../api/types';

type Tab = 'inventory' | 'demand' | 'allocation' | 'files' | 'history';

/**
 * Planner dashboard: tabs for inventory, demand vs inventory, allocation, ingested files and own change history.
 * Editing is possible only at stage 3 (Planning); otherwise the page is read-only apart from uploads.
 * @returns the rendered dashboard page
 */
export default function PlannerDashboard() {
  const [tab, setTab] = useState<Tab>('inventory');
  const cycle = useCycle();
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Planning</h1>
          <p className="muted">
            Inventory and allocation V1 {cycle.data && cycle.data.stage !== 3 && <>· read-only (stage {cycle.data.stage})</>}
          </p>
        </div>
      </div>
      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        tabs={[
          { value: 'inventory', label: 'Inventory' },
          { value: 'demand', label: 'Demand vs Inventory' },
          { value: 'allocation', label: 'Allocation' },
          { value: 'files', label: 'Files' },
          { value: 'history', label: 'History' },
        ]}
      />
      {tab === 'inventory' && <InventoryTab />}
      {tab === 'demand' && <DemandTab />}
      {tab === 'allocation' && <AllocationTab />}
      {tab === 'files' && <FilesTab />}
      {tab === 'history' && (
        <Panel title="My change history" subtitle="Only the changes you made.">
          <AuditTable hideRoleFilter />
        </Panel>
      )}
    </div>
  );
}

/**
 * Available inventory per product: editable at stage 3, upload (any stage) and export.
 * @returns the rendered inventory panel
 */
function InventoryTab() {
  const cycle = useCycle();
  const products = useProducts();
  const inventory = useInventory();
  const canEdit = cycle.data?.stage === 3;
  /** Saves inventory cell edits (comment required). */
  const save = useApiMutation(
    ({ changes, comment }: { changes: CellChange[]; comment: string }) =>
      api.putInventory(
        changes.map((c) => ({ productId: c.productId, qty: c.qty })),
        comment,
      ),
    (r) => `Saved ${r.updated} inventory line${r.updated === 1 ? '' : 's'}`,
  );
  const lines = inventory.data?.lines;
  const columns = useMemo<GridColumn[]>(
    () => [{ type: 'qty', key: 'qty', label: 'Available inventory', values: lines ?? {}, editable: canEdit }],
    [lines, canEdit],
  );
  if (inventory.isLoading || products.isLoading) return <Loading what="inventory" />;
  if (inventory.error) return <QueryError error={inventory.error} />;
  if (products.error) return <QueryError error={products.error} />;
  const ps = products.data ?? [];
  const snap = inventory.data?.snapshot;
  return (
    <Panel
      title="Inventory snapshot"
      subtitle={
        snap ? (
          <>
            Snapshot #{snap.id} · {snap.sourceFile ?? 'manual'} · {snap.uploadedBy} · {fmtTime(snap.createdAt)}
          </>
        ) : (
          'No snapshot yet — upload a file or edit cells.'
        )
      }
    >
      {!canEdit && <Banner kind="info">Inventory is editable only in stage 3 (Planning).</Banner>}
      <EditableGrid
        products={ps}
        columns={columns}
        onSave={canEdit ? (changes, comment) => save.mutateAsync({ changes, comment }) : undefined}
        saveTitle="Save inventory changes"
        toolbar={
          <>
            <UploadButton
              kind="inventory"
              products={ps}
              current={currentFromQty(ps, lines)}
              note={canEdit ? undefined : 'Uploads update inventory at any stage. Allocation approval and final approval re-check that no model is allocated above inventory.'}
            />
            <ExportButton kind="inventory" />
          </>
        }
      />
    </Panel>
  );
}

/**
 * Demand vs inventory: forecast V1 or V2 per region, total demand, inventory and the gap; products with
 * more demand than inventory are flagged as constrained.
 * @returns the rendered demand panel
 */
function DemandTab() {
  const forecast = useForecast();
  const inventory = useInventory();
  const [version, setVersion] = useState<'v1' | 'v2'>('v2');
  const fc = forecast.data;
  const inv = inventory.data?.lines;
  const columns = useMemo<GridColumn[]>(() => demandColumns(fc, version, inv), [fc, version, inv]);
  /**
   * Flags a product as constrained when inventory is below demand.
   * @param eff - value lookup of the row
   * @returns 'warn' or null
   */
  const rowTone = useCallback((eff: Eff): RowTone => {
    const g = eff('gap');
    return g !== null && g < 0 ? 'warn' : null;
  }, []);
  /**
   * "constrained (gap)" note after the product name for constrained products.
   * @param eff - value lookup of the row
   * @returns the flag element, or null
   */
  const rowNote = useCallback((eff: Eff) => {
    const g = eff('gap');
    return g !== null && g < 0 ? <span className="flag warn">constrained ({g})</span> : null;
  }, []);
  if (forecast.isLoading || inventory.isLoading) return <Loading what="demand" />;
  if (forecast.error) return <QueryError error={forecast.error} />;
  if (inventory.error) return <QueryError error={inventory.error} />;
  return (
    <Panel
      title="Demand vs inventory"
      subtitle="Constrained products (demand above inventory) are flagged; R-ALLOC-01 shares them by rule."
      actions={
        <VersionSwitch<'v1' | 'v2'>
          label="Demand"
          value={version}
          onChange={setVersion}
          options={[
            { value: 'v1', label: 'Forecast V1' },
            { value: 'v2', label: 'Forecast V2' },
          ]}
        />
      }
    >
      <EditableGrid products={fc?.products ?? []} columns={columns} rowTone={rowTone} rowNote={rowNote} />
    </Panel>
  );
}

/**
 * Builds the demand-vs-inventory columns: one demand column per region, total demand, inventory and
 * inventory minus demand.
 * @param fc - forecast of the selected month (undefined while loading)
 * @param version - which forecast version is the demand ('v1' or 'v2')
 * @param inv - available inventory per product
 * @returns the grid columns
 */
function demandColumns(fc: ForecastResponse | undefined, version: 'v1' | 'v2', inv: QtyMap | undefined): GridColumn[] {
  const regions = fc?.regions ?? [...REGIONS];
  const cols: GridColumn[] = regions.map((r) => ({
    type: 'qty',
    key: r,
    label: r,
    values: fc ? (fc[version][r] ?? null) : null,
  }));
  cols.push({
    type: 'calc',
    key: 'demand',
    label: 'Total demand',
    calc: (eff) => {
      let s: number | null = null;
      for (const r of regions) {
        const v = eff(r);
        if (v !== null) s = (s ?? 0) + v;
      }
      return s;
    },
  });
  cols.push({ type: 'qty', key: 'inventory', label: 'Inventory', values: inv ?? {} });
  cols.push({
    type: 'calc',
    key: 'gap',
    label: 'Inventory − demand',
    tone: 'balance',
    calc: (eff) => {
      const d = eff('demand');
      const i = eff('inventory');
      return d === null || i === null ? null : i - d;
    },
  });
  return cols;
}

/**
 * Allocation work for the Planner: view V1 / V2 / Final, and at stage 3 run auto-allocation (rule R-ALLOC-01,
 * from forecast V1 or V2), edit V1 cells, upload / export, and approve & send V1 to the Regional Managers.
 * Rule violations from auto-allocation or a blocked submit (R-ALLOC-02) are shown in a banner.
 * @returns the rendered allocation panel and dialogs
 */
function AllocationTab() {
  const cycle = useCycle();
  const products = useProducts();
  const allocation = useAllocation();
  const inventory = useInventory();
  const [version, setVersion] = useState<AllocVersion | null>(null);
  const [autoOpen, setAutoOpen] = useState(false);
  const [basis, setBasis] = useState<1 | 2>(2);
  const [submitOpen, setSubmitOpen] = useState(false);
  const [violations, setViolations] = useState<Violation[] | null>(null);

  const stage = cycle.data?.stage ?? 0;
  const a = allocation.data;
  const v1Status = a?.status.v1 ?? cycle.data?.allocation.v1 ?? null;
  const canEdit = stage === 3 && v1Status !== 'approved' && v1Status !== 'published';
  const v = version ?? (stage >= 4 && a?.v2 ? (a.final ? 'final' : 'v2') : 'v1');
  const editingV1 = v === 'v1' && canEdit;

  /**
   * Runs auto-allocation into V1 from the chosen forecast basis; the toast reports violations.
   */
  const auto = useApiMutation(
    ({ comment, basis }: { comment: string; basis: 1 | 2 }) => api.autoAllocate(comment, basis),
    (r) => `Auto-allocation written to V1${r.violations.length ? ` with ${r.violations.length} violation(s)` : ''}`,
  );
  /** Saves Allocation V1 cell edits (column key = region; comment required). */
  const save = useApiMutation(
    ({ changes, comment }: { changes: CellChange[]; comment: string }) =>
      api.putAllocationV1(
        changes.map((c) => ({ productId: c.productId, region: c.key as Region, qty: c.qty })),
        comment,
      ),
    (r) => `Saved ${r.updated} allocation cell${r.updated === 1 ? '' : 's'}`,
  );
  /**
   * Approves allocation V1 and sends it to the Regional Managers (fails with R-ALLOC-02 violations if over inventory).
   */
  const submit = useApiMutation((c: string) => api.submitAllocation(c || undefined), 'Allocation V1 approved and sent to Regional Managers');

  if (allocation.isLoading || products.isLoading || inventory.isLoading) return <Loading what="allocation" />;
  if (allocation.error) return <QueryError error={allocation.error} />;
  if (products.error) return <QueryError error={products.error} />;
  const ps: Product[] = products.data ?? [];
  const inv = inventory.data?.lines ?? null;

  return (
    <>
      {violations && violations.length > 0 && (
        <Banner kind="danger">
          <strong>Rule violations</strong>
          <ProblemList violations={violations} />
          <button className="btn btn-small" onClick={() => setViolations(null)}>
            Dismiss
          </button>
        </Banner>
      )}
      <Panel
        title="Allocation"
        subtitle={
          <>
            V1 <StatusChip status={v1Status} /> · V2 <StatusChip status={a?.status.v2} /> · Final <StatusChip status={a?.status.final} />
            {stage >= 4 && <> · V2 reflects regional transfers (read-only)</>}
          </>
        }
        actions={
          <>
            <VersionSwitch<AllocVersion>
              value={v}
              onChange={setVersion}
              options={[
                { value: 'v1', label: 'V1' },
                { value: 'v2', label: 'V2', disabled: !a?.v2 },
                { value: 'final', label: 'Final', disabled: !a?.final },
              ]}
            />
            {canEdit && (
              <>
                <button className="btn" onClick={() => setAutoOpen(true)}>
                  ⚙ Auto-allocate
                </button>
                <button className="btn btn-primary" disabled={!a?.v1} onClick={() => setSubmitOpen(true)}>
                  Approve &amp; send V1
                </button>
              </>
            )}
          </>
        }
      >
        {!a?.v1 && v === 'v1' && canEdit && (
          <Banner kind="info">No allocation V1 yet. Run Auto-allocate (R-ALLOC-01) or upload an allocation file.</Banner>
        )}
        {a && (allocationVersionMap(a, v) || editingV1) ? (
          <AllocationGrid
            products={ps}
            allocation={a}
            version={v}
            inventory={inv}
            editable={editingV1}
            onSave={editingV1 ? (changes, comment) => save.mutateAsync({ changes, comment }) : undefined}
            toolbar={
              <>
                <UploadButton
                  kind="allocation"
                  products={ps}
                  current={currentFromMatrix(ps, a.v1)}
                  note={
                    canEdit
                      ? undefined
                      : stage < 3
                        ? 'Before Planning the file prepares a draft allocation V1.'
                        : 'Allocation V1 is already approved: the file is validated and stored, but not applied.'
                  }
                />
                <ExportButton kind="allocation" version={v === 'v1' ? '1' : v === 'v2' ? '2' : 'final'} />
              </>
            }
          />
        ) : (
          <Empty>This version does not exist yet.</Empty>
        )}
      </Panel>

      <CommentModal
        open={autoOpen}
        title="Auto-allocate (R-ALLOC-01)"
        confirmLabel="Run auto-allocation"
        onClose={() => setAutoOpen(false)}
        onSubmit={async (comment) => {
          const r = await auto.mutateAsync({ comment, basis });
          setViolations(r.violations.length ? r.violations : null);
        }}
      >
        <p>Overwrites allocation V1 from forecast demand and current inventory using the configured baseline and sharing rule.</p>
        <label className="field">
          <span>Demand basis</span>
          <select value={basis} onChange={(e) => setBasis(Number(e.target.value) as 1 | 2)}>
            <option value={2}>Forecast V2 (revised, default)</option>
            <option value={1}>Forecast V1</option>
          </select>
        </label>
      </CommentModal>

      <CommentModal
        open={submitOpen}
        title="Approve allocation V1"
        confirmLabel="Approve and send"
        required={false}
        onClose={() => setSubmitOpen(false)}
        onSubmit={async (comment) => {
          try {
            await submit.mutateAsync(comment);
            setViolations(null);
          } catch (e) {
            if (e instanceof ApiError && e.violations.length) setViolations(e.violations);
            throw e;
          }
        }}
      >
        <p>
          Blocked if any product's allocation exceeds inventory (R-ALLOC-02). On success V1 is approved, copied to V2 and the
          cycle moves to Regional change.
        </p>
      </CommentModal>
    </>
  );
}

/**
 * Ingested Excel files (UI uploads and SFTP drops), newest first; long messages open in a dialog.
 * @returns the rendered files panel
 */
function FilesTab() {
  const files = useFiles();
  const [msg, setMsg] = useState<string | null>(null);
  if (files.isLoading) return <Loading what="files" />;
  if (files.error) return <QueryError error={files.error} />;
  const rows = [...(files.data ?? [])].sort((a, b) => b.receivedAt.localeCompare(a.receivedAt));
  return (
    <Panel title="Ingested files" subtitle="Uploads from the UI and upstream SFTP drops.">
      <FilesTable rows={rows} onMessage={setMsg} />
      <Modal open={!!msg} title="File message" onClose={() => setMsg(null)}>
        <pre className="claims">{msg}</pre>
      </Modal>
    </Panel>
  );
}

/**
 * Table of ingested files with time, kind, status, path, uploader and message (long messages truncated).
 * @param props.rows - file records to show
 * @param props.onMessage - called with the full message when a truncated message is clicked
 * @returns the rendered table, or an empty message
 */
function FilesTable({
  rows,
  onMessage,
}: {
  rows: { id: number; path: string; kind: string; status: string; message: string | null; uploadedBy: string; receivedAt: string }[];
  onMessage?: (m: string) => void;
}) {
  if (rows.length === 0) return <Empty>No files yet.</Empty>;
  return (
    <div className="grid-wrap">
      <table className="grid">
        <thead>
          <tr>
            <th>Received</th>
            <th>Kind</th>
            <th>Status</th>
            <th>Path</th>
            <th>By</th>
            <th>Message</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((f) => (
            <tr key={f.id} className={f.status === 'rejected' ? 'row-danger' : undefined}>
              <td className="nowrap">{fmtTime(f.receivedAt)}</td>
              <td>{f.kind}</td>
              <td>
                <StatusChip status={f.status} />
              </td>
              <td className="mono">{f.path}</td>
              <td>{f.uploadedBy}</td>
              <td className="comment">
                {f.message && f.message.length > 80 && onMessage ? (
                  <button className="link" onClick={() => onMessage(f.message!)}>
                    {f.message.slice(0, 80)}…
                  </button>
                ) : (
                  f.message
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
