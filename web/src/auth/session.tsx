import { createContext, useContext, type ReactNode } from 'react';
import type { SessionUser } from './keycloak';

const SessionContext = createContext<SessionUser | null>(null);

/**
 * Makes the signed-in user available to all components below it.
 * @param props.user - the signed-in user
 * @param props.children - the app content
 * @returns the context provider
 */
export function SessionProvider({ user, children }: { user: SessionUser; children: ReactNode }) {
  return <SessionContext.Provider value={user}>{children}</SessionContext.Provider>;
}

/**
 * Signed-in user from `SessionProvider`; throws when used outside it.
 * @returns the `SessionUser`
 */
export function useSession(): SessionUser {
  const u = useContext(SessionContext);
  if (!u) throw new Error('useSession outside SessionProvider');
  return u;
}
