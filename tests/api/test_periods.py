"""Month-year periods: each month runs its own pipeline and versions; uploads can span months and add products."""

import pytest

from pifa_api import clients

A = 1
NOV, DEC, JAN = {"X-Period": "2026-11"}, {"X-Period": "2026-12"}, {"X-Period": "Jan-2027"}


@pytest.fixture()
def files(monkeypatch):
    class Files:
        rows: list = []

    def ingest(kind, filename, content, uploaded_by):
        return {"status": "processed", "path": f"/files/processed/{filename}", "filename": filename, "errors": [],
                "rows": [{"row": i + 2, **r} for i, r in enumerate(Files.rows)]}

    monkeypatch.setattr(clients, "ingest_file", ingest)
    return Files


def upload(api, kind, headers=None, **query):
    return api.post(f"/api/files/{kind}", params=query, headers=headers or {}, data={"comment": "file"},
                    files={"file": (f"{kind}.xlsx", b"PK\x03\x04", "application/octet-stream")})


def put(api, region, qty, headers):
    return api.put(f"/api/forecast/{region}?version=1", headers=headers,
                   json={"changes": [{"productId": A, "qty": qty}], "comment": "plan"})


def test_each_month_has_its_own_cycle_versions_and_stage(api, regions):
    api.as_("admin")
    assert api.post("/api/periods", json={"period": "Nov-2026"}).json()["period"] == "2026-11"
    assert api.post("/api/periods", json={"period": "2026-12"}).json()["stage"] == 1

    api.as_("sm.north")
    assert put(api, "North", 10, NOV).json()["revision"] == 1
    assert put(api, "North", 11, NOV).json()["revision"] == 2
    assert put(api, "North", 50, DEC).json()["revision"] == 1  # numbering is per month
    assert api.get("/api/forecast", headers=NOV).json()["v1"]["North"] == {str(A): 11}
    assert api.get("/api/forecast", headers=DEC).json()["v1"]["North"] == {str(A): 50}
    assert [v["label"] for v in api.get("/api/forecast/North/revisions", headers=DEC).json()] == ["V1"]

    for r in regions:
        api.as_(f"sm.{r.lower()}")
        api.post(f"/api/forecast/{r}/submit", headers=NOV, json={})
    assert api.get("/api/cycle", headers=NOV).json()["stage"] == 2
    cycle_dec = api.get("/api/cycle", headers=DEC).json()
    assert (cycle_dec["stage"], cycle_dec["period"], cycle_dec["periodLabel"]) == (1, "2026-12", "Dec 2026")

    listed = {p["period"]: p["stage"] for p in api.get("/api/periods").json()}
    assert listed["2026-11"] == 2 and listed["2026-12"] == 1

    api.as_("admin")
    api.post("/api/admin/stage", headers=DEC, json={"action": "reset", "comment": "restart December"})
    assert api.get("/api/cycle", headers=NOV).json()["stage"] == 2  # other months untouched


def test_month_column_splits_upload_into_month_versions(api, files):
    api.as_("sm.north")
    files.rows = [
        {"product": "Printer Model A", "values": {"qty": 20}, "month": "2026-11"},
        {"product": "Printer Model A", "values": {"qty": 30}, "month": "2027-01"},
        {"product": "Brand New Printer X1", "values": {"qty": 7}, "month": "2027-01"},
    ]
    body = upload(api, "forecast", region="North").json()
    assert [(p["period"], p["revision"]) for p in body["periods"]] == [("2026-11", 1), ("2027-01", 1)]
    assert body["newProducts"] == ["Brand New Printer X1"]

    jan = api.get("/api/forecast", headers=JAN).json()
    new_id = next(p["id"] for p in jan["products"] if p["name"] == "Brand New Printer X1")
    assert jan["v1"]["North"] == {str(A): 30, str(new_id): 7}
    assert api.get("/api/forecast", headers=NOV).json()["v1"]["North"] == {str(A): 20}
    assert "2027-01" in [p["period"] for p in api.get("/api/periods").json()]  # January opened by the upload


def test_new_product_names_are_added_from_any_upload(api, files):
    api.as_("planner")
    files.rows = [{"product": "Label Printer B900", "values": {"qty": 55}}]
    assert upload(api, "inventory").json()["newProducts"] == ["Label Printer B900"]
    api.as_("sm.east")
    files.rows = [{"product": "Desk Printer Z", "values": {"qty": 4}}]
    body = upload(api, "forecast", region="East").json()
    assert body["newProducts"] == ["Desk Printer Z"] and body["revision"] == 1
    names = [p["name"] for p in api.get("/api/products").json()]
    assert {"Label Printer B900", "Desk Printer Z"} <= set(names)


def test_period_header_errors(api):
    api.as_("sm.north")
    assert api.get("/api/cycle", headers={"X-Period": "13/2026"}).status_code == 422
    assert api.get("/api/cycle", headers={"X-Period": "2030-05"}).status_code == 404
    api.as_("head")
    assert api.post("/api/periods", json={"period": "2026-11"}).status_code == 403


def test_upload_into_a_new_selected_month_opens_it(api, files):
    api.as_("sm.south")
    files.rows = [{"product": "Printer Model A", "values": {"qty": 9}}]
    body = upload(api, "forecast", headers={"X-Period": "2027-03"}, region="South").json()
    assert body["periods"][0]["period"] == "2027-03" and body["revision"] == 1
