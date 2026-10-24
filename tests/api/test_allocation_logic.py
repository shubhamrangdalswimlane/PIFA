"""Who may see and change the allocation logic: Planner read-only, Admin and Head of Sales can edit."""


def test_planner_sees_logic_but_cannot_change_it(api):
    r = api.as_("planner").get("/api/rules/allocation")
    assert r.status_code == 200
    body = r.json()
    assert body["config"]["sharing"] == "PROPORTIONAL" and "R-ALLOC-01" in body["drl"]
    put = api.as_("planner").put("/api/config/rules", json={"baselinePct": 25, "sharing": "UNMET_DEMAND", "comment": "x"})
    assert put.status_code == 403


def test_head_and_admin_change_the_logic(api):
    for who, mode in (("head", "UNMET_DEMAND"), ("admin", "PROPORTIONAL")):
        r = api.as_(who).put("/api/config/rules", json={"baselinePct": 25, "sharing": mode, "comment": "policy change"})
        assert r.status_code == 200 and r.json()["sharing"] == mode
        assert api.as_("planner").get("/api/rules/allocation").json()["config"]["sharing"] == mode


def test_change_needs_a_comment_and_sales_cannot_view(api):
    assert api.as_("head").put("/api/config/rules", json={"baselinePct": 25, "sharing": "PROPORTIONAL", "comment": ""}).status_code == 422
    assert api.as_("sm.north").get("/api/rules/allocation").status_code == 403
