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

from .allocation_math import PROPORTIONAL, REGIONS, UNMET_DEMAND, allocate

PACKAGES = ("forecast", "allocation", "transfer", "approval")

CATALOGUE = [
    ("R-FC-01", "forecast", "Forecast, inventory and allocation quantities must be whole numbers greater than or equal to 0."),
    ("R-FC-02", "forecast", "Every forecast change needs a comment, and a Regional Manager revision needs a reason."),
    ("R-FC-03", "forecast", "A Regional Manager may approve or reject a regional forecast, and a rejection needs a comment."),
    ("R-ALLOC-01", "allocation", "If demand fits inventory allocate the demand, otherwise give each region a configurable baseline "
                                 "(default 25%, capped at demand) and share the rest by unmet demand."),
    ("R-ALLOC-02", "allocation", "The sum of regional allocations per model must not exceed available inventory."),
    ("R-XFER-01", "transfer", "A transfer moves a whole, positive quantity between two different valid regions, "
                              "not more than the source allocation, and needs a comment."),
    ("R-XFER-02", "approval", "Allocations and transfers can only be published by approval at stage 5 (Final approval)."),
    ("R-APPR-01", "approval", "Only the Head of Sales can approve or reject the final allocation, and a rejection needs a comment."),
]


def catalogue() -> list[dict]:
    return [{"id": i, "package": p, "description": d} for i, p, d in CATALOGUE]


# --- helpers ---------------------------------------------------------------------------------------

def whole_non_negative(v) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v) and v >= 0 and v == math.floor(v)


def blank(s) -> bool:
    return s is None or not str(s).strip()


def fmt(v) -> str:
    """12.0 -> "12", 2.5 -> "2.5" for messages."""
    if isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v) and v == round(v) and abs(v) < 1e15:
        return str(int(v))
    return str(v)


def region_index(region) -> int:
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
    """Region reported on a transfer violation: the source region when it is valid."""
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
    unknown = [r for r in values if r not in REGIONS]
    if unknown:
        raise ValueError(f"Unknown region(s) in {what}: {unknown}")


def evaluate(package: str, payload: dict) -> dict:
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


def _evaluate_allocation(payload: dict) -> dict:
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
    allocations: list[dict] = []
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
            # R-ALLOC-01: allocate inventory by demand (only when its inputs are valid; else R-FC-01 reports them).
            shares = allocate(int(inventory), {r: int(demand.get(r, 0)) for r in REGIONS}, pct, sharing)
            allocations += [{"product": product, "region": r, "qty": q} for r, q in shares.items()]
    return {"allocations": allocations, "violations": _fire("allocation", facts)}


def self_test() -> tuple[bool, str]:
    """Health check: the PRD worked example must allocate 25 per region."""
    result = evaluate("allocation", {"mode": "ALLOCATE", "config": {"baselinePct": 25, "sharing": UNMET_DEMAND},
                                     "models": [{"product": "Model A", "inventory": 100, "demand": dict.fromkeys(REGIONS, 25)}]})
    ok = [a["qty"] for a in result["allocations"]] == [25, 25, 25, 25] and not result["violations"]
    return ok, f"{len(RULES)} rule conditions, {len(CATALOGUE)} rules loaded" if ok else "self-test failed"
