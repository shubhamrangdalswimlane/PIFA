import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { lazy, Suspense, type ReactNode } from 'react';
import { BrowserRouter, Link, Navigate, Route, Routes } from 'react-router-dom';
import { ApiError } from './api/client';
import type { Role } from './api/types';
import type { SessionUser } from './auth/keycloak';
import { SessionProvider, useSession } from './auth/session';
import { Layout } from './components/Layout';
import { ToastProvider } from './components/Toast';
import { Loading } from './components/ui';
import { ROLE_ROUTE } from './lib/format';

/**
 * Sales Manager dashboard, loaded on first visit (code-split).
 */
const SalesDashboard = lazy(() => import('./pages/SalesDashboard'));
/**
 * Regional Manager dashboard, loaded on first visit (code-split).
 */
const RegionalDashboard = lazy(() => import('./pages/RegionalDashboard'));
/**
 * Planner dashboard, loaded on first visit (code-split).
 */
const PlannerDashboard = lazy(() => import('./pages/PlannerDashboard'));
/**
 * Head of Sales dashboard, loaded on first visit (code-split).
 */
const HeadDashboard = lazy(() => import('./pages/HeadDashboard'));
/**
 * Admin dashboard, loaded on first visit (code-split).
 */
const AdminDashboard = lazy(() => import('./pages/AdminDashboard'));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      refetchOnWindowFocus: true,
      /**
       * Retries failed queries at most twice, but never for auth, permission, not-found, conflict or validation errors.
       * @param count - number of failures so far
       * @param err - the error of the last attempt
       * @returns true to retry
       */
      retry: (count, err) => !(err instanceof ApiError && [401, 403, 404, 409, 422].includes(err.status)) && count < 2,
    },
  },
});

/**
 * Route guard: renders the page only for users holding the required role, otherwise a "not available" panel.
 * @param props.role - role required for this page
 * @param props.children - the guarded page
 * @returns the page or the not-available panel
 */
function Guard({ role, children }: { role: Role; children: ReactNode }) {
  const user = useSession();
  if (!user.roles.includes(role)) {
    return (
      <div className="panel">
        <h2>Not available for your role</h2>
        <p className="muted">This screen belongs to another role.</p>
        <Link className="btn" to="/">
          Go to my dashboard
        </Link>
      </div>
    );
  }
  return <>{children}</>;
}

/**
 * Start route: redirects to the dashboard of the user's primary role, or explains that no PIFA role is assigned.
 * @returns a redirect or the no-role panel
 */
function Home() {
  const user = useSession();
  if (!user.role) {
    return (
      <div className="panel">
        <h2>No PIFA role assigned</h2>
        <p className="muted">
          Your account has none of the roles SALES_MANAGER, REGIONAL_MANAGER, PLANNER, HEAD_OF_SALES or ADMIN. Ask the
          administrator to assign one, then sign in again.
        </p>
      </div>
    );
  }
  return <Navigate to={ROLE_ROUTE[user.role]} replace />;
}

/**
 * Root component: React Query, toasts, session context, router and the role dashboards (lazy-loaded) inside the layout.
 * @param props.user - the signed-in user
 * @returns the whole application
 */
export function App({ user }: { user: SessionUser }) {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <SessionProvider user={user}>
          <BrowserRouter>
            <Layout>
              <Suspense fallback={<Loading what="dashboard" />}>
                <Routes>
                  <Route path="/" element={<Home />} />
                  <Route path="/sales" element={<Guard role="SALES_MANAGER"><SalesDashboard /></Guard>} />
                  <Route path="/regional" element={<Guard role="REGIONAL_MANAGER"><RegionalDashboard /></Guard>} />
                  <Route path="/planner" element={<Guard role="PLANNER"><PlannerDashboard /></Guard>} />
                  <Route path="/head" element={<Guard role="HEAD_OF_SALES"><HeadDashboard /></Guard>} />
                  <Route path="/admin" element={<Guard role="ADMIN"><AdminDashboard /></Guard>} />
                  <Route path="*" element={<Navigate to="/" replace />} />
                </Routes>
              </Suspense>
            </Layout>
          </BrowserRouter>
        </SessionProvider>
      </ToastProvider>
    </QueryClientProvider>
  );
}
