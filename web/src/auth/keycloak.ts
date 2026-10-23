import Keycloak from 'keycloak-js';
import { REGIONS, ROLES, type Region, type Role } from '../api/types';

export const authConfig = {
  url: import.meta.env.VITE_KEYCLOAK_URL ?? '',
  realm: import.meta.env.VITE_KEYCLOAK_REALM || 'printer-poc',
  clientId: import.meta.env.VITE_KEYCLOAK_CLIENT || 'printer-web',
};

let keycloak: Keycloak | null = null;

export interface SessionUser {
  username: string;
  name: string;
  roles: Role[];
  /** Primary role (first known role in contract order). */
  role: Role | null;
  region: Region | null;
}

/**
 * Initialise Keycloak with Authorization Code + PKCE. Redirects to the login
 * page when there is no session. Tokens stay in memory (keycloak-js instance).
 * @returns a Promise resolving to the signed-in Keycloak instance
 */
export async function initAuth(): Promise<Keycloak> {
  if (!authConfig.url) {
    throw new Error('VITE_KEYCLOAK_URL is not set. Copy .env.example to .env.local and set it.');
  }
  const kc = new Keycloak({ url: authConfig.url, realm: authConfig.realm, clientId: authConfig.clientId });
  /**
   * Refreshes the token when it expires; falls back to a new login if refresh fails.
   */
  kc.onTokenExpired = () => {
    kc.updateToken(30).catch(() => kc.login());
  };
  await kc.init({
    onLoad: 'login-required',
    pkceMethod: 'S256',
    checkLoginIframe: false,
  });
  keycloak = kc;
  return kc;
}

/**
 * Returns a fresh access token (refreshed when it expires within 30 s).
 * @returns a Promise resolving to the bearer token; redirects to sign-in and rejects when the session expired
 */
export async function getAccessToken(): Promise<string> {
  const kc = keycloak;
  if (!kc) throw new Error('Not signed in');
  try {
    await kc.updateToken(30);
  } catch {
    await kc.login();
    throw new Error('Session expired, redirecting to sign-in');
  }
  if (!kc.token) throw new Error('No access token');
  return kc.token;
}

/**
 * Signs the user out of Keycloak and returns to the app's start page.
 * @returns nothing
 */
export function logout(): void {
  void keycloak?.logout({ redirectUri: window.location.origin });
}

/**
 * Claims of the current access token.
 * @returns the decoded token payload, or an empty object when not signed in
 */
export function tokenClaims(): Record<string, unknown> {
  return (keycloak?.tokenParsed as Record<string, unknown> | undefined) ?? {};
}

/**
 * Builds the signed-in user from the token: name, PIFA roles (in contract order), primary role and region.
 * @returns the `SessionUser`
 */
export function sessionUser(): SessionUser {
  const claims = tokenClaims();
  const realmAccess = claims.realm_access as { roles?: unknown } | undefined;
  const rawRoles = Array.isArray(realmAccess?.roles) ? (realmAccess.roles as unknown[]) : [];
  const roles = ROLES.filter((r) => rawRoles.includes(r));
  const rawRegion = claims.region;
  const regionStr = Array.isArray(rawRegion) ? rawRegion[0] : rawRegion;
  const region = REGIONS.find((r) => r.toLowerCase() === String(regionStr ?? '').toLowerCase()) ?? null;
  const username = String(claims.preferred_username ?? claims.sub ?? 'unknown');
  return {
    username,
    name: String(claims.name ?? username),
    roles,
    role: roles[0] ?? null,
    region,
  };
}
