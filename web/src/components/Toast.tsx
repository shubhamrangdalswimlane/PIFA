import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react';
import { ApiError } from '../api/client';
import type { RowError, Violation } from '../api/types';

interface ToastItem {
  id: number;
  kind: 'success' | 'error' | 'info';
  title: string;
  violations?: Violation[];
  errors?: RowError[];
}

interface ToastApi {
  success: (msg: string) => void;
  info: (msg: string) => void;
  error: (err: unknown) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

/**
 * Access to the toast notifications; throws when used outside `ToastProvider`.
 * @returns functions to show success, info and error toasts
 */
export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast outside ToastProvider');
  return ctx;
}

/**
 * Provides toast notifications to the app and renders them (at most five; toasts with rule violations
 * or row errors stay until dismissed, others disappear after a few seconds).
 * @param props.children - the app content
 * @returns the provider with the toast stack
 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);

  /**
   * Removes a toast.
   * @param id - toast id
   * @returns nothing
   */
  const dismiss = useCallback((id: number) => setItems((xs) => xs.filter((x) => x.id !== id)), []);

  /**
   * Adds a toast and schedules its automatic dismissal when it has no detail list.
   * @param item - toast kind, title and optional violations / row errors
   * @returns nothing
   */
  const push = useCallback(
    (item: Omit<ToastItem, 'id'>) => {
      const id = nextId.current++;
      setItems((xs) => [...xs.slice(-4), { ...item, id }]);
      const hasDetail = (item.violations?.length ?? 0) + (item.errors?.length ?? 0) > 0;
      if (!hasDetail) setTimeout(() => dismiss(id), item.kind === 'error' ? 9000 : 4500);
    },
    [dismiss],
  );

  const api = useMemo<ToastApi>(
    () => ({
      success: (title) => push({ kind: 'success', title }),
      info: (title) => push({ kind: 'info', title }),
      /**
       * Shows an error toast; an `ApiError` also lists its rule violations and row errors.
       * @param err - any thrown value
       * @returns nothing
       */
      error: (err) => {
        if (err instanceof ApiError) {
          push({ kind: 'error', title: err.message, violations: err.violations, errors: err.errors });
        } else {
          push({ kind: 'error', title: err instanceof Error ? err.message : String(err) });
        }
      },
    }),
    [push],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="toasts" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={`toast toast-${t.kind}`} role={t.kind === 'error' ? 'alert' : 'status'}>
            <div className="toast-head">
              <strong>{t.title}</strong>
              <button className="icon-btn" aria-label="Dismiss" onClick={() => dismiss(t.id)}>
                ×
              </button>
            </div>
            <ProblemList violations={t.violations} errors={t.errors} />
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

/**
 * Readable list of rule violations and file row errors.
 * @param props.violations - business-rule violations (rule id, product, region, message)
 * @param props.errors - Excel row errors (row number, message)
 * @returns the rendered list, or null when there is nothing to show
 */
export function ProblemList({ violations, errors }: { violations?: Violation[]; errors?: RowError[] }) {
  if (!violations?.length && !errors?.length) return null;
  return (
    <ul className="problems">
      {violations?.map((v, i) => (
        <li key={`v${i}`}>
          <span className="rule-id">{v.ruleId}</span>
          {v.product && <span className="muted"> {v.product}</span>}
          {v.region && <span className="muted"> · {v.region}</span>}
          <span> — {v.message}</span>
        </li>
      ))}
      {errors?.map((e, i) => (
        <li key={`e${i}`}>
          <span className="rule-id">Row {e.row}</span> <span>{e.message}</span>
        </li>
      ))}
    </ul>
  );
}
