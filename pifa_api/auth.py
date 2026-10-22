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
        return self.role != SM or region == self.region


@lru_cache
def _jwks() -> jwt.PyJWKClient:
    s = get_settings()
    return jwt.PyJWKClient(f"{s.realm_base}/protocol/openid-connect/certs", cache_keys=True, lifespan=3600)


def decode_token(token: str, audience: str | None) -> dict:
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
    if creds is None:
        raise HTTPException(401, "Missing bearer token")
    return user_from_claims(decode_token(creds.credentials, get_settings().keycloak_audience))


def require_role(*roles: str):
    def guard(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise forbidden(f"Requires role {' or '.join(roles)}")
        return user

    return guard


def service_caller(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    """Client-credentials token from a PIFA service (files-svc poller)."""
    if creds is None:
        raise HTTPException(401, "Missing bearer token")
    claims = decode_token(creds.credentials, audience=None)
    if claims.get("azp") != get_settings().svc_client_id:
        raise forbidden("Service token from an unexpected client")
    return claims


READ_ALL = (RM, PLANNER, HEAD, ADMIN)
EVERYONE = (SM, RM, PLANNER, HEAD, ADMIN)
