"""Excel uploads: Sales Manager and Planner at every stage, never the Regional Manager."""

import pytest

from pifa_api import clients

from .test_workflow import run_forecast, run_planning

A = 1
PRODUCT_A = "Printer Model A"


@pytest.fixture()
def files(monkeypatch):
    """Stand-in for files-svc: every upload parses to the rows set on `files.rows`."""

    class Files:
        rows: list = []

    def ingest(kind, filename, content, uploaded_by):
        return {"status": "processed", "path": f"/files/processed/{filename}", "filename": filename,
                "rows": [{"row": i + 2, "product": p, "values": v} for i, (p, v) in enumerate(Files.rows)], "errors": []}

    monkeypatch.setattr(clients, "ingest_file", ingest)
    return Files


def upload(api, kind, comment="file", **query):
    return api.post(f"/api/files/{kind}", params=query, data={"comment": comment},
                    files={"file": (f"{kind}.xlsx", b"PK\x03\x04", "application/octet-stream")})


def test_sales_manager_upload_applies_while_open(api, files):
    files.rows = [(PRODUCT_A, {"qty": 40})]
    api.as_("sm.north")
    r = upload(api, "forecast", region="North", version=1).json()
    assert r["revision"] == 1 and r["applied"] == 1
    assert api.get("/api/forecast").json()["v1"]["North"] == {str(A): 40}


def test_sales_manager_upload_and_edit_after_submit(api, files, regions):
    run_forecast(api, regions)  # North submitted V1 at 25, all approved: stage 3
    files.rows = [(PRODUCT_A, {"qty": 70})]
    api.as_("sm.north")
    body = upload(api, "forecast", region="North", version=1).json()
    assert body["revision"] == 2 and body["applied"] == 1
    r = api.put("/api/forecast/North?version=1", json={"changes": [{"productId": A, "qty": 72}], "comment": "tweak"})
    assert r.json() == {"updated": 1, "revision": 3}

    me = api.get("/api/forecast").json()
    assert me["v1"]["North"] == {str(A): 72}  # Sales Manager sees the working copy
    assert me["status"]["North"]["v1Rev"] == 3 and me["status"]["North"]["v1SubmittedRev"] == 1
    assert me["status"]["North"]["v1"] == "submitted"  # editing after submit does not reopen or resubmit

    # Reviewers and planning keep the submitted version.
    api.as_("rm.north")
    assert api.get("/api/forecast").json()["v1"]["North"] == {str(A): 25}
    api.as_("head")
    assert api.get("/api/summary").json()["byRegion"]["North"]["forecastV1"] == 25


def test_regional_manager_cannot_upload(api, files, regions):
    for r in regions:
        api.as_(f"sm.{r.lower()}")
        api.post(f"/api/forecast/{r}/submit", json={})
    files.rows = [(PRODUCT_A, {"qty": 5})]
    api.as_("rm.north")
    assert upload(api, "forecast", region="North", version=2).status_code == 403


def test_planner_uploads_inventory_and_allocation_at_any_stage(api, files, regions):
    api.as_("planner")
    files.rows = [(PRODUCT_A, {"qty": 100})]
    assert upload(api, "inventory").json()["applied"] == 1  # stage 1
    files.rows = [(PRODUCT_A, {"North": 10, "East": 10, "West": 10, "South": 10})]
    assert upload(api, "allocation").json()["applied"] == 4  # V1 draft prepared early

    run_forecast(api, regions)
    run_planning(api)  # V1 approved, stage 4
    api.as_("planner")
    files.rows = [(PRODUCT_A, {"qty": 90})]
    assert upload(api, "inventory").json()["applied"] == 1
    files.rows = [(PRODUCT_A, {"North": 1, "East": 1, "West": 1, "South": 1})]
    late = upload(api, "allocation").json()
    assert late["applied"] == 0 and "already approved" in late["message"]
    # Cell edits keep their stage-3 rule.
    assert api.put("/api/inventory", json={"changes": [{"productId": A, "qty": 5}], "comment": "x"}).status_code == 409
