"""Head of Sales approves or rejects transfers one by one, or all at once, at final approval."""

from .test_workflow import run_forecast, run_planning

A = 1


def to_final_approval(api, regions, moves):
    run_forecast(api, regions)
    run_planning(api)  # 25 per region
    ids = []
    for src, dst, qty in moves:
        api.as_("rm.north")
        r = api.post("/api/transfers", json={"productId": A, "fromRegion": src, "toRegion": dst, "qty": qty, "comment": "move"})
        ids.append(r.json()["id"])
    for r in regions:
        api.as_(f"rm.{r.lower()}")
        api.post("/api/allocation/confirm", json={})
    api.as_("head")
    return ids


def v2(api, regions):
    alloc = api.get("/api/allocation").json()["v2"]
    return [alloc[r][str(A)] for r in regions]


def test_approve_and_reject_each(api, regions):
    t1, t2 = to_final_approval(api, regions, [("East", "North", 5), ("West", "South", 10)])
    assert v2(api, regions) == [30, 20, 15, 35]

    assert api.post(f"/api/transfers/{t1}/approve", json={}).json()["status"] == "approved"
    assert api.post(f"/api/transfers/{t2}/reject", json={"comment": ""}).status_code == 422
    rejected = api.post(f"/api/transfers/{t2}/reject", json={"comment": "South has enough"}).json()
    assert (rejected["status"], rejected["decidedBy"], rejected["decisionComment"]) == ("rejected", "head", "South has enough")
    assert v2(api, regions) == [30, 20, 25, 25]  # rejected units moved back
    assert api.post(f"/api/transfers/{t1}/reject", json={"comment": "x"}).status_code == 409  # already decided

    assert api.post("/api/allocation/approve", json={}).status_code == 200
    final = api.get("/api/allocation").json()["final"]
    assert [final[r][str(A)] for r in regions] == [30, 20, 25, 25]
    assert {t["id"]: t["status"] for t in api.get("/api/transfers").json()} == {t1: "approved", t2: "rejected"}


def test_approve_all_and_only_head_at_stage_5(api, regions):
    ids = to_final_approval(api, regions, [("East", "North", 5), ("West", "South", 3)])
    api.as_("planner")
    assert api.post(f"/api/transfers/{ids[0]}/approve", json={}).status_code == 403
    api.as_("head")
    assert api.post("/api/transfers/approve-all", json={"comment": "fine"}).json() == {"approved": 2}
    assert all(t["status"] == "approved" for t in api.get("/api/transfers").json())
    assert api.get("/api/summary").json()["transfersPending"] == 0


def test_publish_approves_remaining_pending(api, regions):
    ids = to_final_approval(api, regions, [("East", "North", 5), ("West", "South", 3)])
    api.post(f"/api/transfers/{ids[1]}/reject", json={"comment": "no"})
    api.post("/api/allocation/approve", json={})
    statuses = {t["id"]: (t["status"], t["decidedBy"]) for t in api.get("/api/transfers").json()}
    assert statuses == {ids[0]: ("approved", "head"), ids[1]: ("rejected", "head")}
