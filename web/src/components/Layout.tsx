import type { ReactNode } from 'react';
import { NavLink } from 'react-router-dom';
import { useCycle } from '../api/hooks';
import type { Cycle } from '../api/types';
import { logout } from '../auth/keycloak';
import { useSession } from '../auth/session';
import { ROLE_LABEL, ROLE_ROUTE, STAGES } from '../lib/format';

export function StageTracker({ cycle }: { cycle: Cycle | undefined }) {
  const stage = cycle?.stage ?? 0;
  return (
    <div className="stage-tracker" aria-label="Workflow stage">
      <ol>
        {STAGES.map((s) => {
          const state = stage > s.n || stage === 6 ? 'done' : stage === s.n ? 'current' : 'todo';
          return (
            <li key={s.n} className={`stage stage-${state}${s.n === 6 ? ' stage-published' : ''}`} aria-current={state === 'current' ? 'step' : undefined}>
              <span className="stage-num">{state === 'done' ? '✓' : s.n === 6 ? '★' : s.n}</span>
              <span className="stage-text">
                <span className="stage-label">{s.label}</span>
                {s.actor && <span className="stage-actor">{s.actor}</span>}
              </span>
            </li>
          );
        })}
      </ol>
      <div className="next-actor">
        {cycle ? (
          stage === 6 ? (
            <>Allocation published</>
          ) : (
            <>
              Next to act: <strong>{cycle.nextActor || '—'}</strong>
            </>
          )
        ) : (
          <span className="muted">Loading cycle…</span>
        )}
      </div>
    </div>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  const user = useSession();
  const cycle = useCycle();

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo" aria-hidden>
            ▤
          </span>
          <div>
            <div className="brand-name">PIFA</div>
            <div className="brand-sub">Inventory Allocation</div>
          </div>
        </div>
        <nav className="nav">
          {user.roles.map((r) => (
            <NavLink key={r} to={ROLE_ROUTE[r]}>
              {ROLE_LABEL[r]}
            </NavLink>
          ))}
        </nav>
        <div className="cycle-name">
          {cycle.data ? (
            <>
              <span className="muted small">Cycle</span> <strong>{cycle.data.name}</strong>
            </>
          ) : cycle.error ? (
            <span className="danger small">Cycle unavailable</span>
          ) : null}
        </div>
        <div className="spacer" />
        <div className="user">
          <div className="user-name">{user.name}</div>
          <div className="user-meta">
            {user.role ? ROLE_LABEL[user.role] : 'No role'}
            {user.region && <> · {user.region}</>}
          </div>
        </div>
        <button className="btn" onClick={logout}>
          Log out
        </button>
      </header>
      <StageTracker cycle={cycle.data} />
      <main className="content">{children}</main>
    </div>
  );
}
