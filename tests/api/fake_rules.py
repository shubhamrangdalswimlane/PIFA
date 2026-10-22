"""Python stand-in for the Drools service with the same contract (docs/API_CONTRACT.md §2).

Only used by API tests; the real rules and their tests live in rules/.
"""

REGIONS = ["North", "East", "West", "South"]


def _v(rule, product, message, region=None):
    return {"ruleId": rule, "product": product, "region": region, "message": message}


def _whole(q) -> bool:
    return float(q).is_integer() and q >= 0


def fake_rules(package: str, payload: dict) -> dict:
    violations = []
    if package == "forecast":
        for c in payload.get("changes", []):
            if not _whole(c["qty"]):
                violations.append(_v("R-FC-01", c["product"], "Quantity must be a whole number >= 0", c.get("region")))
            if not (c.get("comment") or "").strip():
                violations.append(_v("R-FC-02", c["product"], "Comment required", c.get("region")))
        review = payload.get("review")
        if review and review["decision"] == "REJECT" and not (review.get("comment") or "").strip():
            violations.append(_v("R-FC-03", None, "Rejection needs a comment"))
        return {"violations": violations}

    if package == "allocation":
        allocations = []
        for m in payload["models"]:
            if payload["mode"] == "VALIDATE":
                total = sum(m["allocated"].values())
                if total > m["inventory"]:
                    violations.append(_v("R-ALLOC-02", m["product"], f"Allocated {total} exceeds inventory {m['inventory']}"))
                continue
            demand, inv = m["demand"], m["inventory"]
            if sum(demand.values()) <= inv:
                share = dict(demand)
            else:
                total = sum(demand.values())
                share = {r: inv * demand[r] // total for r in REGIONS}
                for r in sorted(REGIONS, key=lambda r: -(inv * demand[r] % total)):
                    if sum(share.values()) < inv:
                        share[r] += 1
            allocations += [{"product": m["product"], "region": r, "qty": share[r]} for r in REGIONS]
        return {"allocations": allocations, "violations": violations}

    if package == "transfer":
        t = payload["transfer"]
        if t["fromRegion"] == t["toRegion"] or not _whole(t["qty"]) or t["qty"] <= 0 or t["qty"] > t["sourceQty"] \
                or not (t.get("comment") or "").strip():
            violations.append(_v("R-XFER-01", t["product"], "Invalid transfer"))
        return {"violations": violations}

    if package == "approval":
        r = payload["request"]
        if r["actorRole"] != "HEAD_OF_SALES":
            violations.append(_v("R-APPR-01", None, "Only Head of Sales approves"))
        if r["decision"] == "REJECT" and not (r.get("comment") or "").strip():
            violations.append(_v("R-APPR-01", None, "Rejection needs a comment"))
        if r["decision"] == "APPROVE" and r["stage"] != 5:
            violations.append(_v("R-XFER-02", None, "Publish only at final approval"))
        return {"violations": violations}

    raise AssertionError(f"unexpected rules package {package}")
