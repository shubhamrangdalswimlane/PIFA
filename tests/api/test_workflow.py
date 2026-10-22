"""End-to-end API cycle plus visibility and control checks (PRD §2 success metrics)."""

import psycopg
import pytest

from pifa_api.config import get_settings

A = 1  # "Printer Model A" is the first seeded product


def stage(api) -> int:
    return api.get("/api/cycle").json()["stage"]


def run_forecast(api, regions, qty=25):
    for r in regions:
        api.as_(f"sm.{r.lower()}")
        assert api.put(f"/api/forecast/{r}?version=1", json={"changes": [{"productId": A, "qty": qty}],
                                                             "comment": "plan"}).status_code == 200
        assert api.post(f"/api/forecast/{r}/submit", json={}).status_code == 200
    for r in regions:
        api.as_(f"rm.{r.lower()}")
        assert api.post(f"/api/forecast/{r}/approve", json={}).status_code == 200


def run_planning(api, inventory=100):
    api.as_("planner")
    assert api.put("/api/inventory", json={"changes": [{"productId": A, "qty": inventory}], "comment": "stock"}).status_code == 200
    r = api.post("/api/allocation/auto", json={"comment": "auto"})
    assert r.status_code == 200, r.text
    assert api.post("/api/allocation/submit", json={}).status_code == 200


def test_full_cycle_worked_example(api, regions):
    """PRD §4: Model A, 100 units, 25 each; East→North 5 gives 30/20/25/25, published only after Head approval."""
    run_forecast(api, regions)
    assert stage(api) == 3
    run_planning(api)
    assert stage(api) == 4
    alloc = api.get("/api/allocation").json()
    assert [alloc["v1"][r][str(A)] for r in regions] == [25, 25, 25, 25]

    api.as_("rm.north")
    t = api.post("/api/transfers", json={"productId": A, "fromRegion": "East", "toRegion": "North", "qty": 5,
                                         "comment": "North promo"})
    assert t.status_code == 200, t.text
    v2 = api.get("/api/allocation").json()["v2"]
    assert [v2[r][str(A)] for r in regions] == [30, 20, 25, 25]

    for r in regions:
        api.as_(f"rm.{r.lower()}")
        assert api.post("/api/allocation/confirm", json={}).status_code == 200
    assert stage(api) == 5

    api.as_("head")
    assert api.post("/api/allocation/reject", json={"comment": ""}).status_code == 422
    assert api.post("/api/allocation/reject", json={"comment": "Check West"}).status_code == 200
    cycle = api.get("/api/cycle").json()
    assert cycle["stage"] == 4 and all(v is None for v in cycle["confirmations"].values())

    for r in regions:
        api.as_(f"rm.{r.lower()}")
        api.post("/api/allocation/confirm", json={})
    api.as_("head")
    assert api.post("/api/allocation/approve", json={"comment": "ok"}).status_code == 200
    final = api.get("/api/allocation").json()
    assert final["status"]["final"] == "published"
    assert [final["final"][r][str(A)] for r in regions] == [30, 20, 25, 25]
    assert api.get("/api/transfers").json()[0]["status"] == "approved"
    assert stage(api) == 6

    # Every business edit has a comment (PRD metric: 100%).
    audit = api.get("/api/audit?limit=5000").json()
    assert audit and all((e["comment"] or "").strip() for e in audit if e["entity"] in ("forecast", "inventory", "allocation", "transfer"))


def test_sales_manager_sees_only_own_region(api):
    api.as_("sm.north")
    body = api.get("/api/forecast").json()
    assert body["regions"] == ["North"] and list(body["v1"]) == ["North"]
    assert api.put("/api/forecast/East?version=1", json={"changes": [{"productId": A, "qty": 1}], "comment": "x"}).status_code == 403
    assert api.get("/api/inventory").status_code == 403
    assert list(api.get("/api/allocation").json()["regions"]) == ["North"]


def test_comment_and_whole_number_required(api):
    api.as_("sm.north")
    r = api.put("/api/forecast/North?version=1", json={"changes": [{"productId": A, "qty": 5}], "comment": " "})
    assert r.status_code == 422 and r.json()["detail"]["violations"][0]["ruleId"] == "R-FC-02"
    r = api.put("/api/forecast/North?version=1", json={"changes": [{"productId": A, "qty": 2.5}], "comment": "x"})
    assert r.status_code == 422 and r.json()["detail"]["violations"][0]["ruleId"] == "R-FC-01"


def test_regional_manager_writes_only_own_region(api, regions):
    for r in regions:
        api.as_(f"sm.{r.lower()}")
        api.post(f"/api/forecast/{r}/submit", json={})
    api.as_("rm.north")
    assert api.put("/api/forecast/East?version=2", json={"changes": [{"productId": A, "qty": 1}], "comment": "x"}).status_code == 403
    assert api.put("/api/forecast/North?version=2", json={"changes": [{"productId": A, "qty": 9}], "comment": "x"}).status_code == 200
    assert api.post("/api/forecast/East/approve", json={}).status_code == 403


def test_reject_returns_region_to_sales_manager(api, regions):
    for r in regions:
        api.as_(f"sm.{r.lower()}")
        api.post(f"/api/forecast/{r}/submit", json={})
    api.as_("rm.east")
    assert api.post("/api/forecast/East/reject", json={"comment": ""}).status_code == 422
    assert api.post("/api/forecast/East/reject", json={"comment": "Too low"}).status_code == 200
    assert api.get("/api/cycle").json()["forecast"]["East"] == {"v1": "rejected", "v2": "rejected"}
    api.as_("sm.east")
    assert api.put("/api/forecast/East?version=1", json={"changes": [{"productId": A, "qty": 40}], "comment": "fixed"}).status_code == 200
    assert api.post("/api/forecast/East/submit", json={}).status_code == 200
    assert api.get("/api/cycle").json()["forecast"]["East"] == {"v1": "submitted", "v2": "draft"}


def test_allocation_above_inventory_is_blocked(api, regions):
    run_forecast(api, regions)
    api.as_("planner")
    api.put("/api/inventory", json={"changes": [{"productId": A, "qty": 50}], "comment": "stock"})
    api.put("/api/allocation/v1", json={"changes": [{"productId": A, "region": r, "qty": 20} for r in regions],
                                        "comment": "manual"})
    r = api.post("/api/allocation/submit", json={})
    assert r.status_code == 422 and r.json()["detail"]["violations"][0]["ruleId"] == "R-ALLOC-02"
    assert stage(api) == 3


def test_transfer_rules_and_undo(api, regions):
    run_forecast(api, regions)
    run_planning(api)
    api.as_("rm.west")
    assert api.post("/api/transfers", json={"productId": A, "fromRegion": "East", "toRegion": "East", "qty": 1,
                                            "comment": "x"}).status_code == 422
    assert api.post("/api/transfers", json={"productId": A, "fromRegion": "East", "toRegion": "West", "qty": 26,
                                            "comment": "x"}).status_code == 422
    t = api.post("/api/transfers", json={"productId": A, "fromRegion": "East", "toRegion": "West", "qty": 10,
                                         "comment": "x"}).json()
    api.as_("rm.north")
    assert api.post(f"/api/transfers/{t['id']}/undo", json={"comment": "no"}).status_code == 403
    api.as_("rm.west")
    assert api.post(f"/api/transfers/{t['id']}/undo", json={"comment": "changed mind"}).json()["status"] == "undone"
    v2 = api.get("/api/allocation").json()["v2"]
    assert [v2[r][str(A)] for r in regions] == [25, 25, 25, 25]


def test_only_head_publishes_and_admin_cannot(api, regions):
    run_forecast(api, regions)
    run_planning(api)
    api.as_("admin")
    assert api.post("/api/admin/stage", json={"action": "advance", "comment": "unblock"}).json()["stage"] == 5
    assert api.post("/api/admin/stage", json={"action": "advance", "comment": "skip"}).status_code == 409
    api.as_("planner")
    assert api.post("/api/allocation/approve", json={}).status_code == 403


def test_admin_override_is_audited(api):
    api.as_("admin")
    assert api.post("/api/admin/stage", json={"action": "advance", "comment": ""}).status_code == 422
    assert api.post("/api/admin/stage", json={"action": "advance", "comment": "North blocked"}).json()["stage"] == 2
    entries = api.get("/api/audit?entity=workflow").json()
    assert any(e["status"] == "override" and "North blocked" in e["comment"] for e in entries)


def test_audit_log_is_append_only(api):
    api.as_("sm.north")
    api.put("/api/forecast/North?version=1", json={"changes": [{"productId": A, "qty": 5}], "comment": "x"})
    with psycopg.connect(get_settings().database_url, options="-c search_path=pifa", autocommit=True) as c:
        with pytest.raises(psycopg.errors.RaiseException):
            c.execute("UPDATE audit_log SET comment = 'tampered'")
        with pytest.raises(psycopg.errors.RaiseException):
            c.execute("DELETE FROM audit_log")


def test_summary_kpis(api, regions):
    run_forecast(api, regions)
    run_planning(api)
    api.as_("head")
    s = api.get("/api/summary").json()
    assert s["forecastV1"] == 100 and s["inventory"] == 100 and s["allocated"] == 100 and s["transfersPending"] == 0
