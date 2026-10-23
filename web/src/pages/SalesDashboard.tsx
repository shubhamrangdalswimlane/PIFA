import { useMemo, useState } from 'react';
import { api } from '../api/client';
import { useApiMutation, useCycle, useForecast, useNextRevision } from '../api/hooks';
import type { QtyChange, Rejection } from '../api/types';
import { useSession } from '../auth/session';
import { AuditTable } from '../components/AuditTable';
import { EditableGrid, type CellChange, type GridColumn } from '../components/EditableGrid';
import { UploadButton } from '../components/ExcelTools';
import { CommentModal } from '../components/Modal';
import { useToast } from '../components/Toast';
import { VersionHistory } from '../components/VersionHistory';
import { Banner, Loading, Panel, QueryError, RegionTag, StatusChip } from '../components/ui';
import { currentFromQty } from '../lib/excel';
import { fmtTime } from '../lib/format';

/**
 * Sales Manager dashboard for their own region: edit or upload the forecast (each save becomes the next
 * version V<n>), export the current version, submit it to the Regional Manager (stages 1–2), see a
 * rejection reason, browse / compare / restore own versions and see own change history.
 * @returns the rendered dashboard page
 */
export default function SalesDashboard() {
  const { region } = useSession();
  const cycle = useCycle();
  const forecast = useForecast();
  const toast = useToast();
  const [submitOpen, setSubmitOpen] = useState(false);

  const status = region ? forecast.data?.status[region] : undefined;
  const v1Status = status?.v1 ?? cycle.data?.forecast[region ?? 'North']?.v1 ?? null;
  const stage = cycle.data?.stage ?? 0;
  // The forecast is always editable (each save is a new version); submitting is a stage 1-2 step.
  const canSubmit = (stage === 1 || stage === 2) && (v1Status === 'draft' || v1Status === 'rejected' || v1Status === null);

  const salesRev = status?.v1Rev ?? null;
  const submittedRev = status?.v1SubmittedRev ?? null;
  const nextRev = useNextRevision(region);

  /**
   * Saves edits to the Sales Manager forecast (version 1); the toast names the new version or says nothing changed.
   */
  const save = useApiMutation(
    ({ changes, comment }: { changes: QtyChange[]; comment: string }) => api.putForecast(region!, 1, changes, comment),
    (r) =>
      r.revision
        ? `Saved as version V${r.revision} (${r.updated} line${r.updated === 1 ? '' : 's'} changed)`
        : 'No changes — no new version created',
  );
  /**
   * Submits the current version to the Regional Manager (optional comment).
   */
  const submit = useApiMutation(
    (comment: string) => api.submitForecast(region!, comment || undefined),
    `Forecast submitted${salesRev ? ` — V${salesRev} sent to the Regional Manager` : ''}`,
  );

  const v1 = region ? forecast.data?.v1[region] : undefined;

  const columns = useMemo<GridColumn[]>(
    () => [{ type: 'qty', key: 'v1', label: `Forecast${salesRev ? ` (V${salesRev})` : ''}`, values: v1, editable: true }],
    [v1, salesRev],
  );

  if (!region) return <Banner kind="danger">Your account has no region claim. Ask the administrator to set it.</Banner>;
  if (forecast.isLoading) return <Loading what="forecast" />;
  if (forecast.error) return <QueryError error={forecast.error} />;
  const products = forecast.data?.products ?? [];

  /**
   * Saves the grid edits to the Sales Manager forecast (version 1) as a new version.
   * @param changes - edited cells
   * @param comment - required reason
   * @returns a Promise resolving to the save result (rejects on failure so the dialog stays open)
   */
  const onSave = (changes: CellChange[], comment: string) =>
    save.mutateAsync({ changes: changes.map((c) => ({ productId: c.productId, qty: c.qty })), comment });

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Sales forecast</h1>
          <p className="muted">
            <RegionTag region={region} own /> Current version <span className="version-badge">{salesRev ? `V${salesRev}` : 'none yet'}</span>
            {submittedRev && (
              <>
                {' '}
                · Submitted <span className="version-badge">V{submittedRev}</span>
              </>
            )}{' '}
            · Status <StatusChip status={v1Status} />
          </p>
        </div>
        <div className="page-actions">
          {canSubmit && (
            <button className="btn btn-primary" onClick={() => setSubmitOpen(true)}>
              Submit V{salesRev ?? 1}
            </button>
          )}
        </div>
      </div>

      {v1Status === 'rejected' && <RejectionBanner rejection={status?.rejection} />}
      {submittedRev && v1Status !== 'rejected' && salesRev !== submittedRev && (
        <Banner kind="info">
          You have saved changes after submitting: V{submittedRev} is with the Regional Manager, your current version is V{salesRev}. Later
          versions are kept in your history{canSubmit ? ' and can be submitted' : ''}.
        </Banner>
      )}

      <Panel
        title="Forecast by product"
        subtitle={`Edit cells and save with a comment, or upload Excel files and then edit. Each save creates the next version (V${nextRev}).`}
      >
        <EditableGrid
          products={products}
          columns={columns}
          onSave={onSave}
          saveTitle={`Save as version V${nextRev} — ${region}`}
          toolbar={
            <>
              <UploadButton
                kind="forecast"
                region={region}
                version={1}
                multiple
                label="Upload Excel"
                products={products}
                current={currentFromQty(products, v1)}
              />
              <button
                className="btn"
                disabled={!salesRev}
                title={salesRev ? `Download V${salesRev} as Excel` : 'Nothing saved yet'}
                onClick={() => salesRev && api.exportRevision(region, salesRev).catch(toast.error)}
              >
                ⇩ Export{salesRev ? ` V${salesRev}` : ''}
              </button>
            </>
          }
        />
      </Panel>

      <VersionHistory
        region={region}
        products={products}
        title={`My versions — ${region}`}
        subtitle="Only the versions you saved. Every save (dashboard edit or Excel file) creates the next version."
        currentSales={salesRev}
        submitted={submittedRev}
        canRestore
        restoreHint="Copy this version into your forecast as a new version"
      />

      <Panel title="My change history" subtitle="Only the changes you made.">
        <AuditTable fixedRegion={region} hideRoleFilter showExport={false} limit={1000} />
      </Panel>

      <CommentModal
        open={submitOpen}
        title={`Submit ${region} forecast`}
        confirmLabel={`Submit V${salesRev ?? 1}`}
        required={false}
        placeholder="Optional note for the Regional Manager"
        onClose={() => setSubmitOpen(false)}
        onSubmit={(c) => submit.mutateAsync(c)}
      >
        <p>
          Version <strong>V{salesRev ?? 1}</strong> goes to the Regional Manager for <strong>{region}</strong>, who reviews and revises it. You
          can keep editing afterwards; your new versions stay in your history and do not change what was submitted unless the forecast is
          rejected and you submit again.
        </p>
      </CommentModal>
    </div>
  );
}

/**
 * Red banner telling the Sales Manager the forecast was rejected, quoting the Regional Manager's reason.
 * @param props.rejection - who rejected, when and why (may be missing)
 * @returns the rendered banner
 */
function RejectionBanner({ rejection }: { rejection: Rejection | null | undefined }) {
  return (
    <Banner kind="danger">
      <strong>Rejected by the Regional Manager.</strong> Revise your forecast and submit again.
      {rejection?.comment && (
        <div className="quote">
          “{rejection.comment}” <span className="muted small">— {rejection.by}, {fmtTime(rejection.at)}</span>
        </div>
      )}
    </Banner>
  );
}
