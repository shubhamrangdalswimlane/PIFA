import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState, type ReactNode } from 'react';
import { NavLink } from 'react-router-dom';
import { api } from '../api/client';
import { qk, useCycle, usePeriods } from '../api/hooks';
import type { Cycle, PeriodInfo } from '../api/types';
import { logout } from '../auth/keycloak';
import { useSession } from '../auth/session';
import { ROLE_LABEL, ROLE_ROUTE, STAGES } from '../lib/format';
import { getPeriod, setPeriod } from '../period';
import { useToast } from './Toast';
import { Loading, QueryError } from './ui';

/**
 * Workflow bar under the header: the six stages (forecast input … published) marked done / current / to do,
 * plus who has to act next.
 * @param props.cycle - workflow state of the selected month (undefined while loading)
 * @returns the rendered stage tracker
 */
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

/**
 * App shell: header with role navigation, month picker, user name and logout. Chooses a month once the
 * list of months is known (the remembered one if it still exists, else the latest) and renders the page
 * for that month.
 * @param props.children - the routed dashboard page
 * @returns the rendered layout
 */
export function Layout({ children }: { children: ReactNode }) {
  const user = useSession();
  const periods = usePeriods();
  const queryClient = useQueryClient();
  const [period, setSelected] = useState<string | null>(getPeriod());

  // Pick a month once the list is known: the remembered one if it still exists, else the most recently opened.
  useEffect(() => {
    const list = periods.data;
    if (!list?.length) return;
    if (!period || !list.some((p) => p.period === period)) {
      const latest = [...list].sort((a, b) => b.cycleId - a.cycleId)[0].period;
      setPeriod(latest);
      setSelected(latest);
    }
  }, [periods.data, period]);

  /**
   * Switches the whole app to another month: stores it (sent as `X-Period` from now on) and drops all
   * cached month-specific data so the new month loads fresh.
   * @param next - month-year as "YYYY-MM"
   * @returns nothing
   */
  const switchTo = (next: string) => {
    setPeriod(next);
    // Every business query belongs to one month: drop them all so the new month loads fresh.
    queryClient.removeQueries({ predicate: (q) => !['me', 'periods'].includes(String(q.queryKey[0])) });
    setSelected(next);
  };

  const ready = !!period && !!periods.data?.some((p) => p.period === period);

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
        <PeriodPicker periods={periods.data ?? []} value={ready ? period : null} onChange={switchTo} canOpen={user.roles.some((r) => r === 'SALES_MANAGER' || r === 'PLANNER' || r === 'ADMIN')} />
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
      {ready ? (
        <PeriodContent key={period}>{children}</PeriodContent>
      ) : periods.error ? (
        <main className="content">
          <QueryError error={periods.error} />
        </main>
      ) : (
        <main className="content">
          <Loading what="planning months" />
        </main>
      )}
    </div>
  );
}

/**
 * Stage tracker + dashboard for the selected month; remounted when the month changes.
 * @param props.children - the dashboard page
 * @returns the stage tracker and page content
 */
function PeriodContent({ children }: { children: ReactNode }) {
  const cycle = useCycle();
  return (
    <>
      <StageTracker cycle={cycle.data} />
      <main className="content">{children}</main>
    </>
  );
}

/**
 * Header month-year selector; users who may open months (Sales Manager, Planner, Admin) can also open a new month for planning.
 * @param props.periods - months that have a planning cycle
 * @param props.value - selected month, or null while none is ready
 * @param props.onChange - called with the month to switch to (also after opening a new one)
 * @param props.canOpen - shows the "+ Month" button
 * @returns the rendered picker
 */
function PeriodPicker({
  periods,
  value,
  onChange,
  canOpen,
}: {
  periods: PeriodInfo[];
  value: string | null;
  onChange: (period: string) => void;
  canOpen: boolean;
}) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [month, setMonth] = useState('');
  /**
   * Opens a new planning month, refreshes the month list, announces it and switches the app to it.
   */
  const open = useMutation({
    mutationFn: (p: string) => api.createPeriod(p),
    onSuccess: async (p) => {
      await queryClient.invalidateQueries({ queryKey: qk.periods });
      toast.success(`${p.label} is open for planning`);
      setAdding(false);
      setMonth('');
      onChange(p.period);
    },
    onError: (e) => toast.error(e),
  });

  return (
    <div className="period-picker">
      <label className="muted small" htmlFor="period-select">
        Month
      </label>
      <select id="period-select" value={value ?? ''} onChange={(e) => onChange(e.target.value)} disabled={!periods.length}>
        {!value && <option value="">…</option>}
        {periods.map((p) => (
          <option key={p.period} value={p.period}>
            {p.label} · {p.stage === 6 ? 'Published' : `Stage ${p.stage}`}
          </option>
        ))}
      </select>
      {canOpen &&
        (adding ? (
          <span className="period-add">
            <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} aria-label="New planning month" />
            <button className="btn btn-sm btn-primary" disabled={!month || open.isPending} onClick={() => open.mutate(month)}>
              Open
            </button>
            <button className="btn btn-sm" onClick={() => setAdding(false)}>
              Cancel
            </button>
          </span>
        ) : (
          <button className="btn btn-sm" title="Open another month-year for planning" onClick={() => setAdding(true)}>
            ＋ Month
          </button>
        ))}
    </div>
  );
}
