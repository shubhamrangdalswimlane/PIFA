"""Business rules: a passing and a failing case for every rule ID, plus the R-ALLOC-01 maths."""

import random

import pytest

from pifa_api.rules import catalogue, evaluate, self_test
from pifa_api.rules.allocation_math import REGIONS, allocate, largest_remainder

ALL = ["R-FC-01", "R-FC-02", "R-FC-03", "R-ALLOC-01", "R-ALLOC-02", "R-XFER-01", "R-XFER-02", "R-APPR-01"]


def ids(result):
    return [v["ruleId"] for v in result["violations"]]


def change(qty=5, comment="why", revision=False):
    return {"entity": "forecast", "product": "Model A", "region": "North", "qty": qty, "comment": comment, "isRevision": revision}


def alloc(models, mode="ALLOCATE", pct=25, sharing="UNMET_DEMAND"):
    return evaluate("allocation", {"mode": mode, "config": {"baselinePct": pct, "sharing": sharing}, "models": models})


def shares(result, product):
    return [a["qty"] for a in result["allocations"] if a["product"] == product]


def test_catalogue_lists_all_eight_rules():
    assert [r["id"] for r in catalogue()] == ALL
    assert self_test()[0]


# --- forecast package ------------------------------------------------------------------------------

def test_fc01_whole_number_at_least_zero():
    assert ids(evaluate("forecast", {"changes": [change(0), change(12.0)]})) == []
    bad = evaluate("forecast", {"changes": [change(2.5), change(-1), change(None)]})
    assert ids(bad) == ["R-FC-01"] * 3
    assert bad["violations"][0]["message"] == "Quantity -1 must be a whole number >= 0"


def test_fc02_comment_and_revision_reason():
    assert ids(evaluate("forecast", {"changes": [change(comment="ok")]})) == []
    assert evaluate("forecast", {"changes": [change(comment=" ")]})["violations"][0]["message"] == "A comment is required for every change"
    assert "reason" in evaluate("forecast", {"changes": [change(comment="", revision=True)]})["violations"][0]["message"]


def test_fc03_review_rejection_needs_comment():
    ok = {"actorRole": "REGIONAL_MANAGER", "decision": "REJECT", "comment": "too high"}
    assert ids(evaluate("forecast", {"changes": [], "review": ok})) == []
    assert ids(evaluate("forecast", {"changes": [], "review": {**ok, "comment": ""}})) == ["R-FC-03"]
    assert ids(evaluate("forecast", {"changes": [], "review": {**ok, "decision": "MAYBE"}})) == ["R-FC-03"]


# --- allocation package ----------------------------------------------------------------------------

def test_alloc01_worked_example_and_surplus():
    r = alloc([{"product": "A", "inventory": 100, "demand": dict.fromkeys(REGIONS, 25)},
               {"product": "S", "inventory": 500, "demand": {"North": 10, "East": 20}}])
    assert shares(r, "A") == [25, 25, 25, 25]
    assert shares(r, "S") == [10, 20, 0, 0]  # surplus stays unallocated
    assert r["violations"] == []


def test_alloc01_constrained_baseline_then_unmet_demand():
    r = alloc([{"product": "B", "inventory": 100, "demand": {"North": 60, "East": 40, "West": 20, "South": 0}}])
    assert shares(r, "B") == [46, 34, 20, 0] and sum(shares(r, "B")) == 100


def test_alloc01_rounding_ties_and_largest_remainder():
    assert list(allocate(10, dict.fromkeys(REGIONS, 10), 25, "UNMET_DEMAND").values()) == [3, 3, 2, 2]
    assert list(allocate(7, {"North": 10, "East": 6, "West": 3, "South": 1}, 25, "UNMET_DEMAND").values()) == [3, 2, 1, 1]


def test_alloc01_proportional_and_large_baseline():
    assert list(allocate(100, {"North": 60, "East": 40, "West": 20, "South": 0}, 25, "PROPORTIONAL").values()) == [50, 33, 17, 0]
    big = allocate(100, dict.fromkeys(REGIONS, 100), 40, "UNMET_DEMAND")  # baselines 4 x 40 > 100: scaled to fit
    assert sum(big.values()) == 100


def test_alloc01_invalid_inputs_report_fc01_and_skip_allocation():
    r = alloc([{"product": "X", "inventory": 10.5, "demand": {"North": 1}}])
    assert r["allocations"] == [] and ids(r) == ["R-FC-01"]


@pytest.mark.parametrize("seed", range(5))
def test_alloc01_properties_random(seed):
    rng = random.Random(seed)
    for _ in range(1000):
        demand = {r: rng.randint(0, 300) for r in REGIONS}
        inventory = rng.randint(0, 900)
        out = allocate(inventory, demand, rng.choice([0, 10, 25]), rng.choice(["UNMET_DEMAND", "PROPORTIONAL"]))
        assert sum(out.values()) == min(inventory, sum(demand.values()))
        assert all(0 <= out[r] <= demand[r] for r in REGIONS)


def test_largest_remainder_rejects_impossible_split():
    with pytest.raises(ValueError):
        largest_remainder(11, [5, 5])


def test_alloc02_validate_within_inventory():
    ok = alloc([{"product": "A", "inventory": 100, "allocated": dict.fromkeys(REGIONS, 25)}], mode="VALIDATE")
    assert ok == {"allocations": [], "violations": []}
    bad = alloc([{"product": "A", "inventory": 100, "allocated": {"North": 50, "East": 51, "South": 0.5}}], mode="VALIDATE")
    assert ids(bad) == ["R-ALLOC-02", "R-FC-01"]
    assert bad["violations"][0]["message"] == "Allocated 101.5 exceeds inventory 100"


def test_allocation_request_errors():
    with pytest.raises(ValueError):
        alloc([{"product": "A", "inventory": 1, "demand": {"Mars": 1}}])
    with pytest.raises(ValueError):
        alloc([], mode="GUESS")
    with pytest.raises(ValueError):
        alloc([], sharing="RANDOM")


# --- transfer package ------------------------------------------------------------------------------

def transfer(**kw):
    t = {"product": "Model A", "fromRegion": "East", "toRegion": "North", "qty": 5, "sourceQty": 25, "comment": "promo"} | kw
    return evaluate("transfer", {"transfer": t})


def test_xfer01_valid_transfer_prd_example():
    assert transfer()["violations"] == []


@pytest.mark.parametrize("kw", [{"toRegion": "East"}, {"toRegion": "Mars"}, {"qty": 0}, {"qty": 2.5}, {"qty": 26}, {"comment": ""}])
def test_xfer01_invalid_transfers(kw):
    result = transfer(**kw)
    assert ids(result) and set(ids(result)) == {"R-XFER-01"}
    assert all(v["region"] in ("East", None) for v in result["violations"])


# --- approval package ------------------------------------------------------------------------------

def approval(**kw):
    return evaluate("approval", {"request": {"actorRole": "HEAD_OF_SALES", "decision": "APPROVE", "comment": "", "stage": 5} | kw})


def test_appr01_and_xfer02():
    assert ids(approval()) == []
    assert ids(approval(decision="REJECT", comment="recheck")) == []
    assert ids(approval(actorRole="PLANNER", decision="REJECT")) == ["R-APPR-01", "R-APPR-01"]
    assert ids(approval(decision="LATER")) == ["R-APPR-01"]
    assert ids(approval(stage=4)) == ["R-XFER-02"]
