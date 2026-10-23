"""Keycloak JWT validation, role guards and region scoping (Arch §4.2, §7)."""

from dataclasses import dataclass, field
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import get_settings
from .domain import ADMIN, HEAD, PLANNER, REGIONS, RM, ROLES, SM, forbidden

bearer = HTTPBearer(auto_error=False)


@dataclass
class User:
    username: str
    name: str
    role: str
    region: str | None
    claims: dict = field(default_factory=dict)

    def can_read_region(self, region: str) -> bool:
        """Tell whether the user may read a region's data.

        Sales Managers may only read their own region; every other role may read all regions.

        Args:
            region: region name (North, East, West or South).

        Returns:
            True when the region is readable for this user.
        """
        return self.role != SM or region == self.region

    @property
    def own_history_only(self) -> bool:
        """Sales Manager, Regional Manager and Planner see only their own changes; Head and Admin see everything.

        Returns:
            True for Sales Manager, Regional Manager and Planner; False for Head of Sales and Admin.
        """
        return self.role in (SM, RM, PLANNER)

    @property
    def own_versions_only(self) -> bool:
        """Sales and Regional Managers see only forecast versions they created.

        Returns:
            True for Sales Manager and Regional Manager.
        """
        return self.role in (SM, RM)


@lru_cache
def _jwks() -> jwt.PyJWKClient:
    """Build the cached client that fetches the realm's public signing keys (JWKS) from Keycloak.

    Keys are cached for an hour so tokens can be verified without a Keycloak call per request.

    Returns:
        PyJWKClient pointed at the realm's certs endpoint.
    """
    s = get_settings()
    return jwt.PyJWKClient(f"{s.realm_base}/protocol/openid-connect/certs", cache_keys=True, lifespan=3600)


def decode_token(token: str, audience: str | None) -> dict:
    """Verify a Keycloak JWT (RS256 signature, issuer, expiry and optionally audience) and return its claims.

    Args:
        token: raw bearer token.
        audience: expected `aud` claim; None skips the audience check (used for service tokens).

    Returns:
        dict of the token's claims.

    Raises:
        HTTPException: 503 when the Keycloak signing keys cannot be loaded; 401 when the token is invalid or expired.
    """
    s = get_settings()
    try:
        key = _jwks().get_signing_key_from_jwt(token).key
        return jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=s.keycloak_issuer,
            audience=audience,
            options={"verify_aud": audience is not None, "require": ["exp", "iss"]},
            leeway=30,
        )
    except jwt.PyJWKClientError as e:
        raise HTTPException(503, f"Cannot load Keycloak signing keys: {e}") from e
    except jwt.PyJWTError as e:
        raise HTTPException(401, f"Invalid token: {e}") from e


def user_from_claims(claims: dict) -> User:
    """Turn verified token claims into a PIFA user.

    Picks the first PIFA realm role and, for Sales and Regional Managers, the `region` claim.

    Args:
        claims: decoded JWT claims.

    Returns:
        User with username, display name, role, region (None for non-regional roles) and the raw claims.

    Raises:
        HTTPException: 403 when the token has no PIFA role, or a Sales/Regional Manager token has no valid region.
    """
    roles = claims.get("realm_access", {}).get("roles", [])
    role = next((r for r in ROLES if r in roles), None)
    if role is None:
        raise forbidden("Token has no PIFA role")
    region = claims.get("region")
    if role in (SM, RM) and region not in REGIONS:
        raise forbidden("Token has no valid region claim")
    username = claims.get("preferred_username") or claims.get("sub", "unknown")
    return User(
        username=username,
        name=claims.get("name") or username,
        role=role,
        region=region if role in (SM, RM) else None,
        claims=claims,
    )


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> User:
    """FastAPI dependency that authenticates the caller from the `Authorization: Bearer` token.

    Args:
        creds: bearer credentials parsed from the Authorization header (None when the header is missing).

    Returns:
        The signed-in User.

    Raises:
        HTTPException: 401 when the token is missing or invalid; 403 when it carries no PIFA role or region;
            503 when the Keycloak signing keys are unavailable.
    """
    if creds is None:
        raise HTTPException(401, "Missing bearer token")
    return user_from_claims(decode_token(creds.credentials, get_settings().keycloak_audience))


def require_role(*roles: str):
    """Build a FastAPI dependency that only lets callers with one of the given roles through.

    Args:
        *roles: allowed PIFA role names (e.g. SALES_MANAGER, PLANNER).

    Returns:
        A dependency function that returns the signed-in User.
    """
    def guard(user: User = Depends(current_user)) -> User:
        """Check the signed-in caller's role against the allowed roles.

        Args:
            user: signed-in caller (from the JWT).

        Returns:
            The same User when the role is allowed.

        Raises:
            HTTPException: 403 when the caller's role is not one of the allowed roles.
        """
        if user.role not in roles:
            raise forbidden(f"Requires role {' or '.join(roles)}")
        return user

    return guard


def service_caller(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    """Client-credentials token from a PIFA service (files-svc poller).

    Used by the internal endpoints; only tokens issued to the configured service client (`azp`) are accepted.

    Args:
        creds: bearer credentials parsed from the Authorization header (None when the header is missing).

    Returns:
        dict of the service token's claims.

    Raises:
        HTTPException: 401 when the token is missing or invalid; 403 when it was issued to another client.
    """
    if creds is None:
        raise HTTPException(401, "Missing bearer token")
    claims = decode_token(creds.credentials, audience=None)
    if claims.get("azp") != get_settings().svc_client_id:
        raise forbidden("Service token from an unexpected client")
    return claims


READ_ALL = (RM, PLANNER, HEAD, ADMIN)
EVERYONE = (SM, RM, PLANNER, HEAD, ADMIN)
