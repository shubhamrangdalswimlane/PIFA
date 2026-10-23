"""FastAPI application served on Vercel at /api (entry: api/index.py)."""

import logging

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import period, routes_misc, routes_workflow
from .config import get_settings

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="PIFA API", version="1.0.0", docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None,
              dependencies=[Depends(period.from_request)])  # X-Period header selects the month-year

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().allowed_origins.split(",") if o.strip()],
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Authorization", "Content-Type", "X-Period"],
)


@app.middleware("http")
async def security_headers(request, call_next):
    """HTTP middleware that adds `X-Content-Type-Options: nosniff` and `Cache-Control: no-store` to every response.

    Args:
        request: incoming HTTP request.
        call_next: next handler in the middleware chain.

    Returns:
        The downstream response with the headers set (values already present are kept).
    """
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.get("/api/health")
def health():
    """Unauthenticated liveness check.

    Returns:
        {"status": "UP"}
    """
    return {"status": "UP"}


app.include_router(routes_workflow.router)
app.include_router(routes_misc.router)
