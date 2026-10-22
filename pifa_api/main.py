"""FastAPI application served on Vercel at /api (entry: api/index.py)."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import routes_misc, routes_workflow
from .config import get_settings

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="PIFA API", version="1.0.0", docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().allowed_origins.split(",") if o.strip()],
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.get("/api/health")
def health():
    return {"status": "UP"}


app.include_router(routes_workflow.router)
app.include_router(routes_misc.router)
