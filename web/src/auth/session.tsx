import { createContext, useContext, type ReactNode } from 'react';
import type { SessionUser } from './keycloak';

const SessionContext = createContext<SessionUser | null>(null);

export function SessionProvider({ user, children }: { user: SessionUser; children: ReactNode }) {
  return <SessionContext.Provider value={user}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionUser {
  const u = useContext(SessionContext);
  if (!u) throw new Error('useSession outside SessionProvider');
  return u;
}
