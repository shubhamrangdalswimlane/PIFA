"""Business rules entry points plus HTTP clients for Render-hosted services: files-svc and the Keycloak admin API."""

import threading
import time

import httpx
from fastapi import HTTPException

from . import rules as business_rules
from .config import get_settings
from .domain import ROLES, invalid

_token_lock = threading.Lock()
_token: dict = {"value": None, "exp": 0.0}


def service_token() -> str:
    """Client-credentials token for service-to-service calls, cached until shortly before expiry.

    Returns:
        The access token string.

    Raises:
        HTTPException: 503 when Keycloak cannot issue the token.
    """
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
    """Send an authenticated HTTP request to another PIFA service using the cached service token.

    Args:
        service: human-readable service name used in error messages.
        method: HTTP method, e.g. "GET" or "POST".
        url: full request URL.
        **kwargs: extra httpx.request arguments; `headers` are merged and `timeout` defaults to the configured http_timeout.

    Returns:
        The httpx.Response (4xx responses other than 401/403 are returned for the caller to handle).

    Raises:
        HTTPException: 503 when the service is unreachable, answers 5xx, or rejects the service token (401/403).
    """
    s = get_settings()
    headers = kwargs.pop("headers", {}) | {"Authorization": f"Bearer {service_token()}"}
    try:
        r = httpx.request(method, url, headers=headers, timeout=kwargs.pop("timeout", s.http_timeout), **kwargs)
    except httpx.HTTPError as e:
        raise HTTPException(503, f"{service} unavailable: {e}") from e
    if r.status_code >= 500 or r.status_code in (401, 403):
        raise HTTPException(503, f"{service} error {r.status_code}: {r.text[:300]}")
    return r


# --- business rules (Python, in-process; checked before every business write) --------------------

def rules(package: str, payload: dict) -> dict:
    """Run one business rules package in-process (forecast, allocation, transfer or approval).

    Args:
        package: rules package name.
        payload: facts for the package (see docs/API_CONTRACT.md §2).

    Returns:
        The rules result, e.g. {"violations": [...]}; the allocation package also returns "allocations".

    Raises:
        HTTPException: 422 when the request itself is malformed (unknown package, region, mode or sharing); 503 when the Drools KIE Server fails.
    """
    try:
        return business_rules.evaluate(package, payload)
    except ValueError as e:
        raise HTTPException(422, f"Invalid rules request: {e}") from e
    except business_rules.RulesEngineError as e:
        raise HTTPException(503, str(e)) from e


def enforce(package: str, payload: dict, message: str = "Business rule violated") -> dict:
    """Evaluate rules and raise 422 with the violations if any.

    Args:
        package: rules package name.
        payload: facts for the package.
        message: headline of the 422 error.

    Returns:
        The rules result when there are no violations.

    Raises:
        HTTPException: 422 with `message` and the list of violations when any rule fails (or the request is malformed).
    """
    result = rules(package, payload)
    if result.get("violations"):
        raise invalid(message, violations=result["violations"])
    return result


def rules_catalogue() -> list:
    """List every business rule with its ID, package and description (shown on the Rules page).

    Returns:
        list of {"id", "package", "description"} dicts.
    """
    return business_rules.catalogue()


# --- files-svc (SFTP gateway + Excel sandbox) ---------------------------------------------------

def ingest_file(kind: str, filename: str, content: bytes, uploaded_by: str) -> dict:
    """Send an uploaded Excel file to files-svc, which stores it on SFTP and validates and parses it in its sandbox.

    Args:
        kind: file kind: forecast, inventory or allocation.
        filename: original file name.
        content: raw .xlsx bytes.
        uploaded_by: username of the uploader.

    Returns:
        The files-svc ingest result: {"status", "path", "filename", "rows": [...], "errors": [...]}.

    Raises:
        HTTPException: 422 when files-svc rejects the file; 503 when files-svc is unavailable.
    """
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
    """Ask files-svc to build an .xlsx workbook from a table; files-svc also keeps a copy in SFTP /outbound.

    Args:
        filename: workbook file name.
        sheet: worksheet name.
        columns: header row.
        rows: data rows.

    Returns:
        The workbook bytes.

    Raises:
        HTTPException: 503 when the export fails or files-svc is unavailable.
    """
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
    """List the realm's people with their PIFA role and region for the Admin users view (service accounts are skipped).

    Returns:
        list of {"username", "name", "email", "role", "region", "enabled"} sorted by role, region and username.

    Raises:
        HTTPException: 503 when the Keycloak admin API is unavailable.
    """
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
    """Health-check a URL with a short GET request; never raises.

    Args:
        url: URL to check.
        auth: send the service bearer token when True.

    Returns:
        (ok, detail): ok is True for a status below 400; detail is "HTTP <code>" or the error text.
    """
    try:
        headers = {"Authorization": f"Bearer {service_token()}"} if auth else {}
        r = httpx.get(url, headers=headers, timeout=5)
        return r.status_code < 400, f"HTTP {r.status_code}"
    except HTTPException as e:
        return False, str(e.detail)
    except httpx.HTTPError as e:
        return False, str(e)
