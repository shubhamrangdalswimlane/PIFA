"""HTTP clients for Render-hosted services: Drools rules, files-svc and the Keycloak admin API."""

import threading
import time

import httpx
from fastapi import HTTPException

from .config import get_settings
from .domain import ROLES, invalid

_token_lock = threading.Lock()
_token: dict = {"value": None, "exp": 0.0}


def service_token() -> str:
    """Client-credentials token for service-to-service calls, cached until shortly before expiry."""
    with _token_lock:
        if _token["value"] and time.time() < _token["exp"] - 30:
            return _token["value"]
        s = get_settings()
        try:
            r = httpx.post(
                f"{s.realm_base}/protocol/openid-connect/token",
                data={"grant_type": "client_credentials", "client_id": s.svc_client_id, "client_secret": s.svc_client_secret},
                timeout=s.http_timeout,
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise HTTPException(503, f"Keycloak service token unavailable: {e}") from e
        body = r.json()
        _token.update(value=body["access_token"], exp=time.time() + body.get("expires_in", 60))
        return _token["value"]


def _call(service: str, method: str, url: str, **kwargs) -> httpx.Response:
    s = get_settings()
    headers = kwargs.pop("headers", {}) | {"Authorization": f"Bearer {service_token()}"}
    try:
        r = httpx.request(method, url, headers=headers, timeout=kwargs.pop("timeout", s.http_timeout), **kwargs)
    except httpx.HTTPError as e:
        raise HTTPException(503, f"{service} unavailable: {e}") from e
    if r.status_code >= 500 or r.status_code in (401, 403):
        raise HTTPException(503, f"{service} error {r.status_code}: {r.text[:300]}")
    return r


# --- Drools rules service (fail closed: no business write without a decision) -----------------

def rules(package: str, payload: dict) -> dict:
    r = _call("Rules service", "POST", f"{get_settings().rules_url}/rules/{package}", json=payload)
    if r.status_code >= 400:
        raise HTTPException(503, f"Rules service rejected the request: {r.text[:300]}")
    return r.json()


def enforce(package: str, payload: dict, message: str = "Business rule violated") -> dict:
    """Evaluate rules and raise 422 with the violations if any."""
    result = rules(package, payload)
    if result.get("violations"):
        raise invalid(message, violations=result["violations"])
    return result


def rules_catalogue() -> list:
    r = _call("Rules service", "GET", f"{get_settings().rules_url}/rules/catalogue")
    if r.status_code >= 400:
        raise HTTPException(503, f"Rules service error {r.status_code}")
    return r.json()


# --- files-svc (SFTP gateway + Excel sandbox) ---------------------------------------------------

def ingest_file(kind: str, filename: str, content: bytes, uploaded_by: str) -> dict:
    r = _call(
        "File service",
        "POST",
        f"{get_settings().files_url}/ingest/{kind}",
        files={"file": (filename, content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"uploadedBy": uploaded_by},
        timeout=30,
    )
    if r.status_code >= 400:
        try:
            reason = r.json().get("detail", r.text)
        except ValueError:
            reason = r.text
        raise invalid(f"File rejected: {reason}")
    return r.json()


def export_file(filename: str, sheet: str, columns: list, rows: list) -> bytes:
    r = _call(
        "File service",
        "POST",
        f"{get_settings().files_url}/exports",
        json={"filename": filename, "sheet": sheet, "columns": columns, "rows": rows},
        timeout=30,
    )
    if r.status_code >= 400:
        raise HTTPException(503, f"Export failed: {r.text[:300]}")
    return r.content


# --- Keycloak admin (users view, FR-A1) ----------------------------------------------------------

def keycloak_users() -> list[dict]:
    s = get_settings()
    base = f"{s.keycloak_base}/admin/realms/{s.realm}"
    users = _call("Keycloak", "GET", f"{base}/users", params={"max": 200, "briefRepresentation": "false"}).json()
    out = []
    for u in users:
        if u.get("username", "").startswith("service-account-"):
            continue
        roles = _call("Keycloak", "GET", f"{base}/users/{u['id']}/role-mappings/realm").json()
        role_names = [r["name"] for r in roles]
        out.append({
            "username": u["username"],
            "name": " ".join(filter(None, [u.get("firstName"), u.get("lastName")])) or u["username"],
            "email": u.get("email"),
            "role": next((r for r in ROLES if r in role_names), None),
            "region": (u.get("attributes") or {}).get("region", [None])[0],
            "enabled": u.get("enabled", False),
        })
    return sorted(out, key=lambda u: (u["role"] or "", u["region"] or "", u["username"]))


def probe(url: str, auth: bool = False) -> tuple[bool, str]:
    try:
        headers = {"Authorization": f"Bearer {service_token()}"} if auth else {}
        r = httpx.get(url, headers=headers, timeout=5)
        return r.status_code < 400, f"HTTP {r.status_code}"
    except HTTPException as e:
        return False, str(e.detail)
    except httpx.HTTPError as e:
        return False, str(e)
