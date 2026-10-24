import { useEffect, useState } from 'react';
import { api } from '../api/client';
import { useAllocationLogic, useApiMutation } from '../api/hooks';
import { REGIONS, type RuleConfig, type SharingMode } from '../api/types';
import { CommentModal } from './Modal';
import { Loading, Panel, QueryError } from './ui';

const SHARING_LABEL: Record<SharingMode, string> = {
  PROPORTIONAL: 'PROPORTIONAL — every region is cut by the same percentage',
  UNMET_DEMAND: 'UNMET_DEMAND — baseline % per region first, then share the rest by unmet forecast',
};

/**
 * The allocation business logic (rule R-ALLOC-01, run by Drools): engine, current settings, a worked example and the rule text.
 * Admin and Head of Sales (`canEdit`) can change the settings (with a comment); the Planner sees everything read-only.
 * @param props.canEdit - whether the signed-in role may change the settings
 * @returns the rendered panel
 */
export function AllocationLogic({ canEdit = false }: { canEdit?: boolean }) {
  const logic = useAllocationLogic();
  const [draft, setDraft] = useState<RuleConfig | null>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (logic.data) setDraft(logic.data.config);
  }, [logic.data]);
  /**
   * Saves the rule settings (comment required).
   */
  const save = useApiMutation(({ c, comment }: { c: RuleConfig; comment: string }) => api.putRuleConfig(c, comment), 'Allocation logic saved');
  const saved = logic.data?.config;
  const pctValid = draft !== null && Number.isInteger(draft.baselinePct) && draft.baselinePct >= 0 && draft.baselinePct <= 25;
  const dirty = !!draft && !!saved && (draft.baselinePct !== saved.baselinePct || draft.sharing !== saved.sharing);
  const ex = logic.data?.example;

  return (
    <Panel
      title="Allocation logic (Drools)"
      subtitle={canEdit ? 'Used when the Planner auto-allocates. Changes are audited.' : 'Read-only: how the auto-allocation shares inventory between regions.'}
    >
      {logic.isLoading && <Loading what="allocation logic" />}
      {logic.error && <QueryError error={logic.error} />}
      {logic.data && draft && (
        <>
          <p className="small muted">
            Engine: <strong>{logic.data.engine}</strong>. When the forecast fits the inventory every region gets its forecast. When the inventory is
            lower, the rule below shares it.
          </p>
          {canEdit ? (
            <div className="field-row">
              <label className="field">
                <span>Sharing when inventory is lower than forecast</span>
                <select value={draft.sharing} onChange={(e) => setDraft({ ...draft, sharing: e.target.value as SharingMode })}>
                  {(Object.keys(SHARING_LABEL) as SharingMode[]).map((k) => (
                    <option key={k} value={k}>
                      {SHARING_LABEL[k]}
                    </option>
                  ))}
                </select>
              </label>
              {draft.sharing === 'UNMET_DEMAND' && (
                <label className="field narrow">
                  <span>Baseline % per region</span>
                  <input
                    type="number"
                    min={0}
                    max={25}
                    step={1}
                    value={Number.isNaN(draft.baselinePct) ? '' : draft.baselinePct}
                    onChange={(e) => setDraft({ ...draft, baselinePct: e.target.value === '' ? NaN : Number(e.target.value) })}
                  />
                </label>
              )}
              <div className="field">
                <span>&nbsp;</span>
                <div className="button-row">
                  <button className="btn" disabled={!dirty} onClick={() => saved && setDraft(saved)}>
                    Discard
                  </button>
                  <button className="btn btn-primary" disabled={!dirty || !pctValid} onClick={() => setOpen(true)}>
                    Save…
                  </button>
                </div>
              </div>
            </div>
          ) : (
            <p>
              <strong>{SHARING_LABEL[draft.sharing]}</strong>
              {draft.sharing === 'UNMET_DEMAND' && <> · baseline {draft.baselinePct}% per region</>}
            </p>
          )}
          {canEdit && !pctValid && <p className="hint danger">Baseline must be a whole number from 0 to 25.</p>}

          {ex && (
            <div className="grid-wrap">
              <table className="grid">
                <caption className="small muted">Worked example with the current settings: inventory {ex.inventory}</caption>
                <thead>
                  <tr>
                    <th />
                    {REGIONS.map((r) => (
                      <th key={r}>{r}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td className="strong">Forecast</td>
                    {REGIONS.map((r) => (
                      <td key={r}>{ex.demand[r]}</td>
                    ))}
                  </tr>
                  <tr>
                    <td className="strong">Auto allocation</td>
                    {REGIONS.map((r) => (
                      <td key={r} className="strong">
                        {ex.allocation[r]}
                      </td>
                    ))}
                  </tr>
                </tbody>
              </table>
            </div>
          )}
          <details>
            <summary className="small">Rule text (allocation.drl)</summary>
            <pre className="mono small" style={{ overflow: 'auto', maxHeight: 420 }}>
              {logic.data.drl}
            </pre>
          </details>
          <CommentModal
            open={open}
            title="Save allocation logic"
            onClose={() => setOpen(false)}
            onSubmit={(comment) => save.mutateAsync({ c: draft, comment })}
          >
            <p>
              {draft.sharing}
              {draft.sharing === 'UNMET_DEMAND' && <> · baseline {draft.baselinePct}%</>}
            </p>
          </CommentModal>
        </>
      )}
    </Panel>
  );
}
