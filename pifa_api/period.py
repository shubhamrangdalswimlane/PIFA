"""Month-year planning periods.

Every month-year (e.g. 2026-11) runs the full pipeline in its own cycle. The client picks the period with
the `X-Period: 2026-11` header (or `?period=2026-11`); without one the API uses the most recent cycle.
The selected period lives in a context variable for the duration of the request.
"""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime

from fastapi import HTTPException, Request

_current: ContextVar[date | None] = ContextVar("pifa_period", default=None)

_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse(value) -> date:
    """Accepts 2026-11, 2026/11, 11/2026, 11-2026, Nov-2026, Nov 2026, November 2026, Nov-26, or a date. Returns the 1st of the month."""
    if isinstance(value, datetime):
        return date(value.year, value.month, 1)
    if isinstance(value, date):
        return date(value.year, value.month, 1)
    s = str(value or "").strip().lower()
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})(?:[-/.]\d{1,2})?", s)
    if m:
        year, month = int(m.group(1)), int(m.group(2))
    elif m := re.fullmatch(r"(\d{1,2})[-/.](\d{4})", s):
        year, month = int(m.group(2)), int(m.group(1))
    elif m := re.fullmatch(r"([a-z]{3})[a-z]*[\s\-/.']*(\d{2}|\d{4})", s):
        if m.group(1) not in _MONTHS:
            raise ValueError(f"Unknown month '{value}'")
        month, year = _MONTHS[m.group(1)], int(m.group(2))
        year += 2000 if year < 100 else 0
    else:
        raise ValueError(f"'{value}' is not a month-year (use e.g. 2026-11 or Nov-2026)")
    if not (1 <= month <= 12 and 2000 <= year <= 2100):
        raise ValueError(f"'{value}' is not a valid month-year")
    return date(year, month, 1)


def key(p: date) -> str:
    return p.strftime("%Y-%m")


def label(p: date) -> str:
    return p.strftime("%b %Y")


def current() -> date | None:
    return _current.get()


@contextmanager
def use(p: date | None) -> Iterator[None]:
    """Run a block against another period (e.g. rows of an upload for a different month)."""
    token = _current.set(p)
    try:
        yield
    finally:
        _current.reset(token)


async def from_request(request: Request) -> None:
    """App-wide dependency: read the selected period from the X-Period header or ?period=."""
    raw = request.headers.get("x-period") or request.query_params.get("period")
    if not raw:
        _current.set(None)
        return
    try:
        _current.set(parse(raw))
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
