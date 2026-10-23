"""Forecast version history: every save is a new numbered version per region."""

A, B = 1, 2


def put(api, region, version, changes, comment="edit"):
    return api.put(f"/api/forecast/{region}?version={version}",
                   json={"changes": [{"productId": p, "qty": q} for p, q in changes.items()], "comment": comment})


def test_each_sales_manager_save_is_a_new_version(api):
    api.as_("sm.north")
    for i, qty in enumerate([10, 20, 30, 40, 50], start=1):
        r = put(api, "North", 1, {A: qty})
        assert r.json() == {"updated": 1, "revision": i}
    assert put(api, "North", 1, {A: 50}).json() == {"updated": 0, "revision": None}  # no change, no version
    assert put(api, "North", 1, {A: 60, B: 5}).json()["revision"] == 6

    revs = api.get("/api/forecast/North/revisions").json()
    assert [r["label"] for r in revs] == ["V6", "V5", "V4", "V3", "V2", "V1"]
    assert revs[0]["changed"] == 2 and revs[0]["total"] == 65 and revs[0]["stage"] == 1
    assert api.get("/api/forecast/North/revisions/5").json()["lines"] == {str(A): 50}
    assert api.get("/api/forecast").json()["status"]["North"]["v1Rev"] == 6
    assert api.get("/api/forecast/East/revisions").status_code == 403


def test_restore_creates_next_version(api):
    api.as_("sm.north")
    put(api, "North", 1, {A: 10})
    put(api, "North", 1, {A: 99, B: 7})
    r = api.post("/api/forecast/North/revisions/1/restore", json={"comment": "back to first draft"})
    assert r.json() == {"updated": 2, "revision": 3}
    assert api.get("/api/forecast").json()["v1"]["North"] == {str(A): 10, str(B): 0}
    assert api.post("/api/forecast/North/revisions/3/restore", json={"comment": "again"}).status_code == 409


def test_sales_update_during_review_reaches_regional_manager(api, regions):
    for r in regions:
        api.as_(f"sm.{r.lower()}")
        put(api, r, 1, {A: 10})
        api.post(f"/api/forecast/{r}/submit", json={})
    api.as_("rm.north")
    put(api, "North", 2, {A: 11}, "regional view")  # V2
    assert api.post("/api/forecast/North/approve", json={}).status_code == 200

    api.as_("sm.north")
    assert put(api, "North", 1, {A: 30}, "new customer order").json()["revision"] == 3

    api.as_("rm.north")
    body = api.get("/api/forecast").json()
    assert body["v1"]["North"] == {str(A): 30} and body["v2"]["North"] == {str(A): 30}
    st = body["status"]["North"]
    assert (st["v1SubmittedRev"], st["v2Rev"], st["v2"]) == (3, 3, "draft")  # approval withdrawn
    assert api.get("/api/forecast/North/revisions/2").json()["lines"] == {str(A): 11}  # old revision kept


def test_regional_manager_edits_after_approving(api, regions):
    for r in regions:
        api.as_(f"sm.{r.lower()}")
        api.post(f"/api/forecast/{r}/submit", json={})
    api.as_("rm.east")
    api.post("/api/forecast/East/approve", json={})
    assert put(api, "East", 2, {A: 4}, "late change").status_code == 200
    assert api.get("/api/cycle").json()["forecast"]["East"]["v2"] == "draft"


def test_regional_manager_edits_sales_managers_final_version(api, regions):
    api.as_("sm.north")
    put(api, "North", 1, {A: 10})
    put(api, "North", 1, {A: 12})
    for r in regions:
        api.as_(f"sm.{r.lower()}")
        api.post(f"/api/forecast/{r}/submit", json={})
    api.as_("rm.north")
    status = api.get("/api/forecast").json()["status"]["North"]
    assert status["v1Rev"] == 2 and status["v2Rev"] == 2  # RM starts from the submitted V2
    assert api.get("/api/forecast").json()["v2"]["North"] == {str(A): 12}
    assert put(api, "North", 2, {A: 15}, "promo").json()["revision"] == 3
    revs = api.get("/api/forecast/North/revisions").json()
    assert (revs[0]["label"], revs[0]["stage"], revs[0]["role"]) == ("V3", 2, "REGIONAL_MANAGER")
    # V1 (Sales Manager working copy) is untouched by the Regional Manager.
    assert api.get("/api/forecast").json()["v1"]["North"] == {str(A): 12}

    # Untouched regions got a version at submit time (seen by the Head, who sees every version).
    api.as_("head")
    assert [r["source"] for r in api.get("/api/forecast/East/revisions").json()] == ["submit"]
