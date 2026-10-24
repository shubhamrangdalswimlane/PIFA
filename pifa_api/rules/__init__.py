"""PIFA business rules (pure Python; replaces the former Drools service).

Each rule is a small declarative record: the fact type it looks at, a `when` condition and the
violation message. Rule IDs, packages, conditions and messages are the same as the former DRL files,
so the API contract (docs/API_CONTRACT.md §2) is unchanged:

    evaluate("forecast" | "allocation" | "transfer" | "approval", payload) -> {"violations": [...], ...}
    catalogue() -> [{"id", "package", "description"}]

Invalid requests (unknown region, mode or sharing) raise ValueError; business problems come back as
violations, which the API turns into HTTP 422.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..config import get_settings

from . import drools_client
from .allocation_math import PROPORTIONAL, REGIONS, UNMET_DEMAND, allocate
from .drools_client import RulesEngineError

ALLOCATION_DRL = Path(__file__).with_name("allocation.drl")

PACKAGES = ("forecast", "allocation", "transfer", "approval")

CATALOGUE = [
    ("R-FC-01", "forecast", "Forecast, inventory and allocation quantities must be whole numbers greater than or equal to 0."),
    ("R-FC-02", "forecast", "Every forecast change needs a comment, and a Regional Manager revision needs a reason."),
    ("R-FC-03", "forecast", "A Regional Manager may approve or reject a regional forecast, and a rejection needs a comment."),
    ("R-ALLOC-01", "allocation", "Run by Drools. If the forecast fits the inventory every region gets its forecast; otherwise every region "
                                 "is cut by the same percentage (or gets a baseline % first and the rest by unmet forecast)."),
    ("R-ALLOC-02", "allocation", "The sum of regional allocations per model must not exceed available inventory."),
    ("R-XFER-01", "transfer", "A transfer moves a whole, positive quantity between two different valid regions, "
                              "not more than the source allocation, and needs a comment."),
    ("R-XFER-02", "approval", "Allocations and transfers can only be published by approval at stage 5 (Final approval)."),
    ("R-APPR-01", "approval", "Only the Head of Sales can approve or reject the final allocation, and a rejection needs a comment."),
]


def catalogue() -> list[dict]:
    """List every business rule with its ID, package and description.

    Returns:
        list of {"id", "package", "description"} dicts in catalogue order.
    """
    return [{"id": i, "package": p, "description": d} for i, p, d in CATALOGUE]


# --- helpers ---------------------------------------------------------------------------------------

def whole_non_negative(v) -> bool:
    """Check that a quantity is a whole, finite number >= 0 (booleans are rejected); the R-FC-01 test.

    Args:
        v: value taken from the request.

    Returns:
        True when the value is a valid quantity.
    """
    return isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v) and v >= 0 and v == math.floor(v)


def blank(s) -> bool:
    """Tell whether a comment is missing or only whitespace.

    Args:
        s: value to test.

    Returns:
        True when blank.
    """
    return s is None or not str(s).strip()


def fmt(v) -> str:
    """12.0 -> "12", 2.5 -> "2.5" for messages.

    Args:
        v: value to format.

    Returns:
        The value as text, with whole numbers shown without a decimal part.
    """
    if isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v) and v == round(v) and abs(v) < 1e15:
        return str(int(v))
    return str(v)


def region_index(region) -> int:
    """Sort key for regions: position in North, East, West, South, with unknown or missing regions last.

    Args:
        region: region name or None.

    Returns:
        Index in REGIONS, or len(REGIONS) when the region is unknown.
    """
    return REGIONS.index(region) if region in REGIONS else len(REGIONS)


# --- rule definitions ------------------------------------------------------------------------------

@dataclass(frozen=True)
class Rule:
    id: str
    package: str
    fact: str  # fact type the rule matches
    when: Callable[[dict], bool]
    message: Callable[[dict], str]
    product: Callable[[dict], str | None] = lambda f: f.get("product")
    region: Callable[[dict], str | None] = lambda f: f.get("region")


def _transfer_region(t: dict) -> str | None:
    """Region reported on a transfer violation: the source region when it is valid.

    Args:
        t: transfer fact.

    Returns:
        The source region, or None when it is not a valid region.
    """
    return t.get("fromRegion") if t.get("fromRegion") in REGIONS else None


_none = lambda f: None  # noqa: E731 - rules about a decision, not a product/region

RULES: list[Rule] = [
    # forecast: R-FC-01, R-FC-02, R-FC-03
    Rule("R-FC-01", "forecast", "change", lambda c: not whole_non_negative(c.get("qty")),
         lambda c: f"Quantity {fmt(c.get('qty'))} must be a whole number >= 0"),
    Rule("R-FC-02", "forecast", "change", lambda c: not c.get("isRevision") and blank(c.get("comment")),
         lambda c: "A comment is required for every change"),
    Rule("R-FC-02", "forecast", "change", lambda c: bool(c.get("isRevision")) and blank(c.get("comment")),
         lambda c: "A reason is required for a Regional Manager revision"),
    Rule("R-FC-03", "forecast", "review", lambda r: r.get("decision") not in ("APPROVE", "REJECT"),
         lambda r: f"Review decision must be APPROVE or REJECT, got {r.get('decision')}", _none, _none),
    Rule("R-FC-03", "forecast", "review", lambda r: r.get("decision") == "REJECT" and blank(r.get("comment")),
         lambda r: "Rejecting a regional forecast requires a comment for the Sales Manager", _none, _none),
    # allocation: R-ALLOC-02 and R-FC-01 on every quantity (R-ALLOC-01 is the computation in evaluate)
    Rule("R-ALLOC-02", "allocation", "totals", lambda t: t["allocated"] > t["inventory"],
         lambda t: f"Allocated {fmt(t['allocated'])} exceeds inventory {fmt(t['inventory'])}", region=_none),
    Rule("R-FC-01", "allocation", "quantity", lambda q: not whole_non_negative(q.get("qty")),
         lambda q: f"Value of {q['field']} {fmt(q.get('qty'))} must be a whole number >= 0"),
    # transfer: R-XFER-01
    Rule("R-XFER-01", "transfer", "transfer", lambda t: not (t.get("fromRegion") in REGIONS and t.get("toRegion") in REGIONS),
         lambda t: f"Transfer regions must be North, East, West or South (from {t.get('fromRegion')} to {t.get('toRegion')})",
         region=_transfer_region),
    Rule("R-XFER-01", "transfer", "transfer", lambda t: t.get("fromRegion") is not None and t.get("fromRegion") == t.get("toRegion"),
         lambda t: "Transfer must move units between two different regions", region=_transfer_region),
    Rule("R-XFER-01", "transfer", "transfer", lambda t: not (whole_non_negative(t.get("qty")) and t["qty"] > 0),
         lambda t: f"Transfer quantity {fmt(t.get('qty'))} must be a whole number greater than 0", region=_transfer_region),
    Rule("R-XFER-01", "transfer", "transfer",
         lambda t: t.get("qty") is not None and (t.get("sourceQty") is None or t["qty"] > t["sourceQty"]),
         lambda t: f"Transfer quantity {fmt(t.get('qty'))} exceeds source allocation {fmt(t.get('sourceQty'))}",
         region=_transfer_region),
    Rule("R-XFER-01", "transfer", "transfer", lambda t: blank(t.get("comment")),
         lambda t: "A comment is required for every transfer", region=_transfer_region),
    # approval: R-APPR-01, R-XFER-02
    Rule("R-APPR-01", "approval", "approval", lambda a: a.get("actorRole") != "HEAD_OF_SALES",
         lambda a: f"Only HEAD_OF_SALES may approve or reject the final allocation (actor role {a.get('actorRole')})",
         _none, _none),
    Rule("R-APPR-01", "approval", "approval", lambda a: a.get("decision") not in ("APPROVE", "REJECT"),
         lambda a: f"Decision must be APPROVE or REJECT, got {a.get('decision')}", _none, _none),
    Rule("R-APPR-01", "approval", "approval", lambda a: a.get("decision") == "REJECT" and blank(a.get("comment")),
         lambda a: "Rejecting the final allocation requires a comment", _none, _none),
    Rule("R-XFER-02", "approval", "approval", lambda a: a.get("decision") == "APPROVE" and a.get("stage") != 5,
         lambda a: f"Allocation and transfers can only be published from stage 5 (FINAL_APPROVAL), current stage {a.get('stage')}",
         _none, _none),
]


def _fire(package: str, facts: list[tuple[str, dict]]) -> list[dict]:
    """Run every rule of a package against the facts and collect the violations.

    Args:
        package: rules package name.
        facts: (fact type, fact dict) pairs, e.g. ("change", {...}).

    Returns:
        list of {"ruleId", "product", "region", "message"} sorted by rule ID, product, region order and message.
    """
    violations = []
    for rule in (r for r in RULES if r.package == package):
        for kind, fact in facts:
            if kind == rule.fact and rule.when(fact):
                violations.append({"ruleId": rule.id, "product": rule.product(fact), "region": rule.region(fact),
                                   "message": rule.message(fact)})
    # Deterministic output order regardless of rule order.
    violations.sort(key=lambda v: (v["ruleId"], v["product"] or "", region_index(v["region"]), v["message"]))
    return violations


# --- packages --------------------------------------------------------------------------------------

def _check_regions(values: dict, what: str) -> None:
    """Reject region keys that are not North, East, West or South.

    Args:
        values: per-region dict to check.
        what: field name used in the error message.

    Returns:
        None

    Raises:
        ValueError: when an unknown region is present.
    """
    unknown = [r for r in values if r not in REGIONS]
    if unknown:
        raise ValueError(f"Unknown region(s) in {what}: {unknown}")


def evaluate(package: str, payload: dict) -> dict:
    """Evaluate one business rules package against a request payload (in-process replacement of the former Drools service).

    Args:
        package: forecast, allocation, transfer or approval.
        payload: package input: {"changes", "review"?} for forecast, {"mode", "config", "models"} for allocation,
            {"transfer"} for transfer, {"request"} for approval.

    Returns:
        {"violations": [...]}; the allocation package also returns "allocations".

    Raises:
        ValueError: for an unknown package or a malformed payload.
    """
    if package == "forecast":
        facts = [("change", c) for c in payload.get("changes") or [] if c is not None]
        if payload.get("review") is not None:
            facts.append(("review", payload["review"]))
        return {"violations": _fire("forecast", facts)}

    if package == "allocation":
        return _evaluate_allocation(payload)

    if package == "transfer":
        if not isinstance(payload.get("transfer"), dict):
            raise ValueError("Missing 'transfer'")
        return {"violations": _fire("transfer", [("transfer", payload["transfer"])])}

    if package == "approval":
        if not isinstance(payload.get("request"), dict):
            raise ValueError("Missing 'request'")
        return {"violations": _fire("approval", [("approval", payload["request"])])}

    raise ValueError(f"Unknown rules package {package}")


def _shares(models: list[dict], pct: float, sharing: str) -> list[dict]:
    """R-ALLOC-01 arithmetic for several models: on the Drools KIE Server when DROOLS_URL is set, else the Python copy.

    Args:
        models: [{"product", "inventory", "demand": {region: qty}}] with valid quantities.
        pct: baseline percent per region (UNMET_DEMAND only).
        sharing: UNMET_DEMAND or PROPORTIONAL.

    Returns:
        One {region: units} dict per model, in order.

    Raises:
        RulesEngineError: when DROOLS_URL is set and the KIE Server fails (there is no silent fallback).
    """
    s = get_settings()
    if not s.drools_url:
        return [allocate(m["inventory"], m["demand"], pct, sharing) for m in models]
    out = drools_client.allocate(models, sharing, int(pct), s.drools_url, s.drools_user, s.drools_password, s.drools_container)
    return [{r: o[r] for r in REGIONS} for o in out]


def engine_name() -> str:
    """Name of the engine that computes R-ALLOC-01, for the dashboards.

    Returns:
        "Drools (KIE Server)" when DROOLS_URL is set, else "Python (built-in)".
    """
    return "Drools (KIE Server)" if get_settings().drools_url else "Python (built-in)"


def allocation_logic() -> dict:
    """The allocation rule source shown (read-only) to the Planner.

    Returns:
        {"engine": engine name, "drl": text of allocation.drl}.
    """
    return {"engine": engine_name(), "drl": ALLOCATION_DRL.read_text(encoding="utf-8")}


def _evaluate_allocation(payload: dict) -> dict:
    """Evaluate the allocation package for every printer model.

    ALLOCATE mode computes the R-ALLOC-01 shares from inventory and demand; VALIDATE mode checks R-ALLOC-02
    (allocated <= inventory). R-FC-01 is checked on every quantity in both modes.

    Args:
        payload: {"mode": "ALLOCATE" | "VALIDATE", "config": {"baselinePct", "sharing"},
            "models": [{"product", "inventory", "demand": {region: qty}, "allocated": {region: qty}}]}.

    Returns:
        {"allocations": [{"product", "region", "qty"}], "violations": [...]}; allocations is empty in VALIDATE mode.

    Raises:
        ValueError: for an invalid mode, baselinePct, sharing or region.
    """
    mode = payload.get("mode")
    if mode not in ("ALLOCATE", "VALIDATE"):
        raise ValueError("mode must be ALLOCATE or VALIDATE")
    config = payload.get("config") or {}
    pct = config.get("baselinePct", 25)
    sharing = config.get("sharing", UNMET_DEMAND)
    if not isinstance(pct, int | float) or not 0 <= pct <= 100:
        raise ValueError("baselinePct must be between 0 and 100")
    if sharing not in (UNMET_DEMAND, PROPORTIONAL):
        raise ValueError("sharing must be UNMET_DEMAND or PROPORTIONAL")

    facts: list[tuple[str, dict]] = []
    ready: list[dict] = []
    for m in payload.get("models") or []:
        demand, allocated = m.get("demand") or {}, m.get("allocated") or {}
        _check_regions(demand, "demand")
        _check_regions(allocated, "allocated")
        product, inventory = m.get("product"), m.get("inventory")
        facts.append(("quantity", {"product": product, "region": None, "field": "inventory", "qty": inventory}))
        values, field = (demand, "demand") if mode == "ALLOCATE" else (allocated, "allocated")
        for r in REGIONS:
            if r in values:
                facts.append(("quantity", {"product": product, "region": r, "field": field, "qty": values[r]}))
        if mode == "VALIDATE":
            facts.append(("totals", {"product": product, "inventory": inventory or 0,
                                     "allocated": sum(v or 0 for v in allocated.values())}))
        elif whole_non_negative(inventory) and all(whole_non_negative(demand.get(r, 0)) for r in REGIONS):
            # R-ALLOC-01: only when its inputs are valid; otherwise R-FC-01 reports them.
            ready.append({"product": product, "inventory": int(inventory), "demand": {r: int(demand.get(r, 0)) for r in REGIONS}})
    allocations: list[dict] = []
    for m, shares in zip(ready, _shares(ready, pct, sharing), strict=True):
        allocations += [{"product": m["product"], "region": r, "qty": shares[r]} for r in REGIONS]
    return {"allocations": allocations, "violations": _fire("allocation", facts)}


def self_test() -> tuple[bool, str]:
    """Health check: the worked example (forecast 30/20/25/25, inventory 50) must allocate 15/10/13/12 with the active engine.

    Returns:
        (ok, detail): ok is True when the engine allocates as expected; detail names the engine or the failure.
    """
    cfg = {"baselinePct": 25, "sharing": PROPORTIONAL}
    model = {"product": "Model A", "inventory": 50, "demand": {"North": 30, "East": 20, "West": 25, "South": 25}}
    try:
        result = evaluate("allocation", {"mode": "ALLOCATE", "config": cfg, "models": [model]})
    except RulesEngineError as e:
        return False, str(e)[:200]
    got = [a["qty"] for a in result["allocations"]]
    ok = got == [15, 10, 13, 12] and not result["violations"]
    return ok, f"{engine_name()}: {len(CATALOGUE)} rules, example allocates {got}" if ok else f"{engine_name()} self-test failed: {got}"
