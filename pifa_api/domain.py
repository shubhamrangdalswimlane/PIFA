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
    """Build a 409 Conflict error, used when an action does not fit the current workflow state (e.g. wrong stage).

    Args:
        message: explanation for the client.

    Returns:
        HTTPException(409) for the caller to raise.
    """
    return HTTPException(409, message)


def forbidden(message: str = "Not allowed for your role or region") -> HTTPException:
    """Build a 403 Forbidden error for an action the caller's role or region does not allow.

    Args:
        message: explanation for the client.

    Returns:
        HTTPException(403) for the caller to raise.
    """
    return HTTPException(403, message)


def invalid(message: str, violations: list | None = None, errors: list | None = None) -> HTTPException:
    """Build a 422 validation error carrying a message plus optional business-rule violations or file row errors.

    Args:
        message: headline of the error.
        violations: rule violations, each {"ruleId", "product", "region", "message"}.
        errors: row errors from an Excel file.

    Returns:
        HTTPException(422) whose detail is {"message", "violations"?, "errors"?}.
    """
    detail: dict = {"message": message}
    if violations is not None:
        detail["violations"] = violations
    if errors is not None:
        detail["errors"] = errors
    return HTTPException(422, detail)


def require_comment(comment: str | None, what: str = "This change") -> str:
    """R-FC-02 guard applied before any business write (the business rules re-check it).

    Args:
        comment: comment text from the request.
        what: subject used in the error message, e.g. "A rejection".

    Returns:
        The comment without surrounding whitespace.

    Raises:
        HTTPException: 422 with an R-FC-02 violation when the comment is missing or blank.
    """
    if not comment or not comment.strip():
        raise invalid(f"{what} needs a comment", violations=[
            {"ruleId": "R-FC-02", "product": None, "region": None, "message": "A non-empty comment is required"}
        ])
    return comment.strip()


def check_region(region: str) -> str:
    """Validate a region name taken from the URL or request body.

    Args:
        region: region name.

    Returns:
        The same region name.

    Raises:
        HTTPException: 404 when it is not North, East, West or South.
    """
    if region not in REGIONS:
        raise HTTPException(404, f"Unknown region {region}")
    return region
