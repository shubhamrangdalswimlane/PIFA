import { useEffect, useState } from 'react';
import { api } from '../api/client';
import { useAdminUsers, useApiMutation, useCycle, useHealth, useRulesCatalogue } from '../api/hooks';
import { AllocationLogic } from '../components/AllocationLogic';
import { AuditTable } from '../components/AuditTable';
import { DataViews } from '../components/DataViews';
import { StageTracker } from '../components/Layout';
import { CommentModal } from '../components/Modal';
import { Banner, Empty, Loading, Panel, QueryError, StatusChip, Tabs } from '../components/ui';
import { ROLE_LABEL, STAGES } from '../lib/format';

type Tab = 'users' | 'workflow' | 'health' | 'rules' | 'data' | 'audit';

/**
 * Admin dashboard: tabs for users, workflow stage control and rule configuration, integration health,
 * the business rule catalogue, read-only business data and the full audit trail.
 * @returns the rendered dashboard page
 */
export default function AdminDashboard() {
  const [tab, setTab] = useState<Tab>('users');
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Administration</h1>
          <p className="muted">Users, workflow control, integrations and audit. Business data is read-only.</p>
        </div>
      </div>
      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        tabs={[
          { value: 'users', label: 'Users' },
          { value: 'workflow', label: 'Workflow' },
          { value: 'health', label: 'Health' },
          { value: 'rules', label: 'Rules' },
          { value: 'data', label: 'Data' },
          { value: 'audit', label: 'Audit' },
        ]}
      />
      {tab === 'users' && <UsersTab />}
      {tab === 'workflow' && <WorkflowTab />}
      {tab === 'health' && <HealthTab />}
      {tab === 'rules' && <RulesTab />}
      {tab === 'data' && <DataViews />}
      {tab === 'audit' && (
        <Panel title="Audit dashboard">
          <AuditTable />
        </Panel>
      )}
    </div>
  );
}

/**
 * Read-only list of Keycloak users with name, email, PIFA role, region and enabled flag.
 * @returns the rendered users panel
 */
function UsersTab() {
  const users = useAdminUsers();
  if (users.isLoading) return <Loading what="users" />;
  if (users.error) return <QueryError error={users.error} />;
  const rows = users.data ?? [];
  return (
    <Panel title="Users, roles and regions" subtitle="Read from Keycloak realm printer-poc.">
      {rows.length === 0 ? (
        <Empty>No users.</Empty>
      ) : (
        <div className="grid-wrap">
          <table className="grid">
            <thead>
              <tr>
                <th>Username</th>
                <th>Name</th>
                <th>Email</th>
                <th>Role</th>
                <th>Region</th>
                <th>Enabled</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((u) => (
                <tr key={u.username}>
                  <td className="mono">{u.username}</td>
                  <td>{u.name}</td>
                  <td>{u.email}</td>
                  <td>{u.role ? (ROLE_LABEL[u.role as keyof typeof ROLE_LABEL] ?? u.role) : '—'}</td>
                  <td>{u.region ?? '—'}</td>
                  <td>{u.enabled ? <span className="chip chip-approved">yes</span> : <span className="chip chip-rejected">no</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

/**
 * Workflow control: shows the cycle's stage and per-region forecast / allocation statuses, lets the Admin
 * force the next stage (up to stage 5; publishing stays with the Head of Sales) or reset to a new cycle,
 * always with a required comment. Also shows the rule configuration panel.
 * @returns the rendered workflow panels
 */
function WorkflowTab() {
  const cycle = useCycle();
  const [action, setAction] = useState<'advance' | 'reset' | null>(null);
  /**
   * Admin override: advances the stage or resets the cycle (comment required).
   */
  const stage = useApiMutation(
    ({ action, comment }: { action: 'advance' | 'reset'; comment: string }) => api.adminStage(action, comment),
    (c) => `Cycle ${c.name} is now at stage ${c.stage}`,
  );
  const s = cycle.data?.stage ?? 0;
  const label = STAGES.find((x) => x.n === s)?.label ?? '—';
  const canAdvance = s >= 1 && s < 5;

  return (
    <>
      <Panel title="Workflow stage control" subtitle="Every override is written to the audit log with your comment.">
        {cycle.error && <QueryError error={cycle.error} />}
        {cycle.data && (
          <>
            <p>
              <strong>{cycle.data.name}</strong> — stage {s}: {label} <span className="muted">({cycle.data.stageKey})</span>
            </p>
            <StageTracker cycle={cycle.data} />
            <div className="status-table">
              <div>
                <h3>Forecast</h3>
                <table className="grid mini">
                  <thead>
                    <tr>
                      <th>Region</th>
                      <th>V1</th>
                      <th>V2</th>
                      <th>Confirmed</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(cycle.data.forecast).map(([r, st]) => (
                      <tr key={r}>
                        <td>{r}</td>
                        <td>
                          <StatusChip status={st?.v1} />
                        </td>
                        <td>
                          <StatusChip status={st?.v2} />
                        </td>
                        <td>{cycle.data!.confirmations[r as keyof typeof cycle.data.confirmations]?.by ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div>
                <h3>Allocation</h3>
                <p>
                  V1 <StatusChip status={cycle.data.allocation.v1} /> V2 <StatusChip status={cycle.data.allocation.v2} /> Final{' '}
                  <StatusChip status={cycle.data.allocation.final} />
                </p>
              </div>
            </div>
          </>
        )}
        <div className="button-row">
          <button
            className="btn btn-primary"
            disabled={!canAdvance}
            title={s === 5 ? 'Only the Head of Sales can publish (stage 5 → 6)' : undefined}
            onClick={() => setAction('advance')}
          >
            Advance stage
          </button>
          <button className="btn btn-danger" onClick={() => setAction('reset')}>
            Reset cycle…
          </button>
          {s === 5 && <span className="muted small">Stage 5 → 6 requires Head of Sales approval.</span>}
        </div>
      </Panel>
      <AllocationLogic canEdit />
      <CommentModal
        open={!!action}
        title={action === 'reset' ? 'Reset cycle' : 'Advance stage'}
        confirmLabel={action === 'reset' ? 'Reset and start a new cycle' : `Advance to stage ${s + 1}`}
        danger={action === 'reset'}
        placeholder="Reason for this override (required)"
        onClose={() => setAction(null)}
        onSubmit={(comment) => stage.mutateAsync({ action: action!, comment })}
      >
        {action === 'reset' ? (
          <Banner kind="danger">Starts a new, empty cycle at stage 1. The current cycle's data stays in the audit log.</Banner>
        ) : (
          <p>
            Force the cycle from stage {s} ({label}) to stage {s + 1} ({STAGES.find((x) => x.n === s + 1)?.label}).
          </p>
        )}
      </CommentModal>
    </>
  );
}

const HEALTH_LABEL: Record<string, string> = {
  api: 'API (FastAPI)',
  database: 'Database (PostgreSQL)',
  keycloak: 'Keycloak',
  rules: 'Business rules (Drools)',
  files: 'File service',
  sftp: 'SFTP',
};

/**
 * Health cards for the API, database, Keycloak, rules engine, file service and SFTP, with a refresh button.
 * @returns the rendered health panel
 */
function HealthTab() {
  const health = useHealth();
  return (
    <Panel
      title="Integration health"
      actions={
        <button className="btn" disabled={health.isFetching} onClick={() => void health.refetch()}>
          {health.isFetching ? 'Checking…' : '↻ Refresh'}
        </button>
      }
    >
      {health.isLoading && <Loading what="health" />}
      {health.error && <QueryError error={health.error} />}
      {health.data && (
        <div className="health-grid">
          {Object.entries(health.data).map(([k, h]) => (
            <div key={k} className={`health-card ${h.ok ? 'ok' : 'down'}`}>
              <span className="health-dot" aria-hidden />
              <div>
                <div className="strong">{HEALTH_LABEL[k] ?? k}</div>
                <div className="small muted">{h.ok ? 'Healthy' : 'Unavailable'}</div>
                {h.detail && <div className="small mono">{h.detail}</div>}
              </div>
            </div>
          ))}
        </div>
      )}
      {health.dataUpdatedAt > 0 && <p className="muted small">Checked {new Date(health.dataUpdatedAt).toLocaleTimeString()}</p>}
    </Panel>
  );
}

/**
 * Read-only table of the business rules (id, package, description).
 * @returns the rendered rule catalogue panel
 */
function RulesTab() {
  const rules = useRulesCatalogue();
  if (rules.isLoading) return <Loading what="rules" />;
  if (rules.error) return <QueryError error={rules.error} />;
  return (
    <Panel title="Business rule catalogue">
      <div className="grid-wrap">
        <table className="grid">
          <thead>
            <tr>
              <th>ID</th>
              <th>Package</th>
              <th>Description</th>
            </tr>
          </thead>
          <tbody>
            {(rules.data ?? []).map((r) => (
              <tr key={r.id}>
                <td className="mono strong nowrap">{r.id}</td>
                <td>{r.package}</td>
                <td className="comment">{r.description}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
