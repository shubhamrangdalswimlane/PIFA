"""Shared constants and errors."""

from fastapi import HTTPException

REGIONS = ["North", "East", "West", "South"]
ROLES = ["SALES_MANAGER", "REGIONAL_MANAGER", "PLANNER", "HEAD_OF_SALES", "ADMIN"]

SM, RM, PLANNER, HEAD, ADMIN = ROLES

STAGES = {
    1: "FORECAST_INPUT",
    2: "REGIONAL_REVIEW",
    3: "PLANNING",
    4: "REGIONAL_CHANGE",
    5: "FINAL_APPROVAL",
    6: "PUBLISHED",
}


def conflict(message: str) -> HTTPException:
    return HTTPException(409, message)


def forbidden(message: str = "Not allowed for your role or region") -> HTTPException:
    return HTTPException(403, message)


def invalid(message: str, violations: list | None = None, errors: list | None = None) -> HTTPException:
    detail: dict = {"message": message}
    if violations is not None:
        detail["violations"] = violations
    if errors is not None:
        detail["errors"] = errors
    return HTTPException(422, detail)


def require_comment(comment: str | None, what: str = "This change") -> str:
    """R-FC-02 guard applied before any business write (Drools re-checks it)."""
    if not comment or not comment.strip():
        raise invalid(f"{what} needs a comment", violations=[
            {"ruleId": "R-FC-02", "product": None, "region": None, "message": "A non-empty comment is required"}
        ])
    return comment.strip()


def check_region(region: str) -> str:
    if region not in REGIONS:
        raise HTTPException(404, f"Unknown region {region}")
    return region
