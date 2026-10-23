"""Who sees which history: Sales Manager, Regional Manager and Planner only their own; Head and Admin everything."""

from .test_workflow import run_forecast

A = 1


def usernames(api):
    return {e["username"] for e in api.get("/api/audit?limit=5000").json()}


def test_change_history_is_own_only_for_sm_rm_planner(api, regions):
    run_forecast(api, regions)  # SMs edit + submit, RMs approve
    api.as_("planner")
    api.put("/api/inventory", json={"changes": [{"productId": A, "qty": 100}], "comment": "stock"})

    for user in ("sm.north", "rm.east", "planner"):
        api.as_(user)
        assert usernames(api) == {user}, user
        export = api.get("/api/export/audit")  # export uses the same scope
        assert export.status_code == 200

    for user in ("head", "admin"):
        api.as_(user)
        assert {"sm.north", "sm.east", "rm.east", "planner"} <= usernames(api)


def test_version_history_is_own_only_for_sm_and_rm(api, regions):
    api.as_("sm.north")
    api.put("/api/forecast/North?version=1", json={"changes": [{"productId": A, "qty": 10}], "comment": "v1"})
    for r in regions:
        api.as_(f"sm.{r.lower()}")
        api.post(f"/api/forecast/{r}/submit", json={})
    api.as_("rm.north")
    api.put("/api/forecast/North?version=2", json={"changes": [{"productId": A, "qty": 12}], "comment": "regional"})

    api.as_("sm.north")
    assert [v["label"] for v in api.get("/api/forecast/North/revisions").json()] == ["V1"]
    assert api.get("/api/forecast/North/revisions/2").status_code == 404  # the Regional Manager's version
    api.as_("rm.north")
    assert [v["label"] for v in api.get("/api/forecast/North/revisions").json()] == ["V2"]
    assert api.get("/api/forecast/North/revisions/1").status_code == 404  # the Sales Manager's version
    assert api.get("/api/export/forecast?region=North&rev=1").status_code == 404
    api.as_("head")
    assert [v["label"] for v in api.get("/api/forecast/North/revisions").json()] == ["V2", "V1"]


def test_sales_manager_still_sees_rejection_comment(api, regions):
    for r in regions:
        api.as_(f"sm.{r.lower()}")
        api.post(f"/api/forecast/{r}/submit", json={})
    api.as_("rm.west")
    api.post("/api/forecast/West/reject", json={"comment": "Too low for Q4"})
    api.as_("sm.west")
    rejection = api.get("/api/forecast").json()["status"]["West"]["rejection"]
    assert (rejection["by"], rejection["comment"]) == ("rm.west", "Too low for Q4")
