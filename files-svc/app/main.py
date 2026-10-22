"""files-svc: HTTPS gateway to the private SFTP server, Excel sandbox and inbound poller (Render)."""

import logging
import os
import posixpath
import re
import threading
import time
from contextlib import asynccontextmanager
from functools import lru_cache

import httpx
import jwt
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import excel
from .storage import ROOT, make_storage

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("files-svc")

ISSUER = os.environ.get("KEYCLOAK_ISSUER", "http://localhost:8080/realms/printer-poc")
KEYCLOAK_INTERNAL_URL = os.environ.get("KEYCLOAK_INTERNAL_URL", "").rstrip("/")
SVC_CLIENT_ID = os.environ.get("SVC_CLIENT_ID", "printer-api-svc")
SVC_CLIENT_SECRET = os.environ.get("SVC_CLIENT_SECRET", "")
UPSTREAM_CLIENT_ID = os.environ.get("UPSTREAM_CLIENT_ID", "printer-upstream")
API_URL = os.environ.get("API_URL", "").rstrip("/")
POLL_SECONDS = int(os.environ.get("POLL_SECONDS", "60"))
AUTH_DISABLED = os.environ.get("AUTH_DISABLED", "false").lower() == "true"
KINDS = ("forecast", "inventory", "allocation")

storage = make_storage()


def realm_base() -> str:
    if KEYCLOAK_INTERNAL_URL:
        return f"{KEYCLOAK_INTERNAL_URL}/realms/{ISSUER.rstrip('/').rsplit('/', 1)[-1]}"
    return ISSUER.rstrip("/")


@lru_cache
def jwks() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(f"{realm_base()}/protocol/openid-connect/certs", cache_keys=True, lifespan=3600)


def caller(*clients: str):
    def verify(request: Request) -> str:
        if AUTH_DISABLED:
            return "local"
        auth = request.headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            raise HTTPException(401, "Missing bearer token")
        token = auth[7:]
        try:
            key = jwks().get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=["RS256"], issuer=ISSUER, options={"verify_aud": False}, leeway=30)
        except jwt.PyJWTError as e:
            raise HTTPException(401, f"Invalid token: {e}") from e
        if claims.get("azp") not in clients:
            raise HTTPException(403, "Client not allowed")
        return claims["azp"]

    return verify


def safe_name(name: str) -> str:
    base = posixpath.basename(name.replace("\\", "/")) or "upload.xlsx"
    return re.sub(r"[^A-Za-z0-9._-]", "_", base)[:120]


def process(kind: str, path: str, filename: str, content: bytes) -> dict:
    """Validate + parse a stored inbound file, then move it to /processed or /rejected (with a reason file)."""
    try:
        excel.check_container(filename, content)
        rows, errors = excel.parse(kind, content)
    except excel.FileRejected as e:
        rows, errors = [], e.errors
    if not rows and not errors:
        errors = [{"row": 0, "message": "No data rows found"}]
    status = "rejected" if errors else "processed"
    dest = posixpath.join(ROOT, status, posixpath.basename(path))
    storage.move(path, dest)
    if errors:
        reason = "\n".join(f"row {e['row']}: {e['message']}" for e in errors)
        storage.put(dest + ".reason.txt", reason.encode())
    log.info("%s %s -> %s (%d rows, %d errors)", kind, filename, dest, len(rows), len(errors))
    return {"status": status, "path": dest, "filename": filename, "rows": rows if not errors else [], "errors": errors}


# --- poller for files dropped via /upstream (or left behind by a crash) --------------------------

_svc_token = {"value": None, "exp": 0.0}


def service_token() -> str:
    if _svc_token["value"] and time.time() < _svc_token["exp"] - 30:
        return _svc_token["value"]
    r = httpx.post(f"{realm_base()}/protocol/openid-connect/token", timeout=10, data={
        "grant_type": "client_credentials", "client_id": SVC_CLIENT_ID, "client_secret": SVC_CLIENT_SECRET})
    r.raise_for_status()
    body = r.json()
    _svc_token.update(value=body["access_token"], exp=time.time() + body.get("expires_in", 60))
    return _svc_token["value"]


def poll_once() -> int:
    handled = 0
    for kind in KINDS:
        folder = posixpath.join(ROOT, "inbound", kind)
        for path in storage.list(folder):
            name = posixpath.basename(path)
            if name.startswith("gw_"):
                continue  # owned by an in-flight /ingest request
            result = process(kind, path, name, storage.get(path))
            handled += 1
            if API_URL:
                message = "; ".join(f"row {e['row']}: {e['message']}" for e in result["errors"][:20]) or f"{len(result['rows'])} rows validated"
                try:
                    httpx.post(f"{API_URL}/api/internal/ingest", timeout=10,
                               headers={"Authorization": f"Bearer {service_token()}"},
                               json={"path": result["path"], "kind": kind, "status": result["status"],
                                     "message": message, "uploadedBy": "upstream"}).raise_for_status()
                except httpx.HTTPError as e:
                    log.warning("could not report %s to API: %s", result["path"], e)
    return handled


def poller(stop: threading.Event) -> None:
    while not stop.wait(POLL_SECONDS):
        try:
            poll_once()
        except Exception:  # noqa: BLE001 - keep polling
            log.exception("poll failed")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    stop = threading.Event()
    if POLL_SECONDS > 0:
        threading.Thread(target=poller, args=(stop,), daemon=True).start()
    if AUTH_DISABLED:
        log.warning("AUTH_DISABLED=true: service is unauthenticated (local use only)")
    yield
    stop.set()


app = FastAPI(title="PIFA files-svc", lifespan=lifespan)


@app.get("/health")
def health():
    ok, detail = storage.health()
    return {"status": "UP", "sftp": {"ok": ok, "detail": detail}}


@app.post("/ingest/{kind}")
def ingest(kind: str, file: UploadFile = File(...), uploadedBy: str = Form("unknown"),
           _: str = Depends(caller(SVC_CLIENT_ID))):
    if kind not in KINDS:
        raise HTTPException(404, f"Unknown kind {kind}")
    content = file.file.read(excel.MAX_BYTES + 1)
    if len(content) > excel.MAX_BYTES:
        raise HTTPException(413, "File larger than 4 MB")
    filename = safe_name(file.filename or "upload.xlsx")
    path = posixpath.join(ROOT, "inbound", kind, f"gw_{excel.stamp()}_{safe_name(uploadedBy)}_{filename}")
    storage.put(path, content)
    return process(kind, path, filename, content)


class ExportBody(BaseModel):
    filename: str
    sheet: str = "Sheet1"
    columns: list[str]
    rows: list[list] = Field(max_length=100_000)


@app.post("/exports")
def export(body: ExportBody, _: str = Depends(caller(SVC_CLIENT_ID))):
    content = excel.build(body.sheet, body.columns, body.rows)
    filename = safe_name(body.filename)
    storage.put(posixpath.join(ROOT, "outbound", f"{excel.stamp()}_{filename}"), content)
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.post("/upstream/{kind}")
def upstream(kind: str, file: UploadFile = File(...), _: str = Depends(caller(UPSTREAM_CLIENT_ID))):
    if kind not in KINDS:
        raise HTTPException(404, f"Unknown kind {kind}")
    content = file.file.read(excel.MAX_BYTES + 1)
    if len(content) > excel.MAX_BYTES:
        raise HTTPException(413, "File larger than 4 MB")
    path = posixpath.join(ROOT, "inbound", kind, f"{excel.stamp()}_{safe_name(file.filename or 'upload.xlsx')}")
    storage.put(path, content)
    return {"path": path}
