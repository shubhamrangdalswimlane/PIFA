"""Runs the allocation rules (allocation.drl) on a Drools KIE Server through python-drools-sdk.

The KIE Server holds the compiled rules as container "pifa". For every printer model we insert one `Model` fact
(inventory, regional forecasts, sharing mode, baseline %) and the rules fill in the regional allocations.
"""

import threading
from dataclasses import dataclass

from .allocation_math import REGIONS

PACKAGE = "com.pifa.rules"
_lock = threading.Lock()  # python-drools-sdk keeps its command list and settings on the class: one request at a time


class RulesEngineError(Exception):
    """The Drools KIE Server could not be reached or refused the request (mapped to HTTP 503 by the API)."""


@dataclass
class Model:
    """Python mirror of the `Model` type declared in allocation.drl (field names must match)."""

    id: str
    product: str
    inventory: int
    sharing: str
    baselinePct: int
    northDemand: int
    eastDemand: int
    westDemand: int
    southDemand: int
    northAlloc: int = 0
    eastAlloc: int = 0
    westAlloc: int = 0
    southAlloc: int = 0
    status: str = "NEW"
    ruleApplied: str = ""
    pool: int = 0
    totalWeight: int = 0
    leftover: int = 0


def _drools():
    """Import python-drools-sdk (done late so the API still starts when only the Python rules are used).

    Returns:
        The (Drools, InsertObjectCommand, DroolsException) classes of the SDK.

    Raises:
        RulesEngineError: when the package is not installed.
    """
    try:
        from python_drools_sdk.commands.insert_object_command import InsertObjectCommand
        from python_drools_sdk.exceptions.drools_exception import DroolsException
        from python_drools_sdk.kie.drools import Drools
    except ImportError as e:  # pragma: no cover - depends on the environment
        raise RulesEngineError("python-drools-sdk is not installed") from e
    return Drools, InsertObjectCommand, DroolsException


def allocate(models: list[dict], sharing: str, baseline_pct: int, url: str, user: str, password: str, container: str) -> list[dict]:
    """Ask the KIE Server to allocate the inventory of several printer models.

    Args:
        models: [{"product", "inventory", "demand": {region: qty}}], quantities already validated as whole numbers >= 0.
        sharing: PROPORTIONAL or UNMET_DEMAND.
        baseline_pct: baseline percent per region (UNMET_DEMAND only).
        url: KIE Server root URL, e.g. http://kie:8080.
        user: KIE Server user.
        password: KIE Server password.
        container: KIE container id that holds the rules.

    Returns:
        One dict per input model, in order: {"North": qty, "East": qty, "West": qty, "South": qty, "rule": rule applied}.

    Raises:
        RulesEngineError: when the server is unreachable, rejects the request or answers without a result.
    """
    if not models:
        return []
    drools, insert_command, drools_error = _drools()
    with _lock:
        drools.KIE_SERVER_ROOT_URL = url.rstrip("/")
        drools.KIE_SERVER_USERNAME, drools.KIE_SERVER_PASSWORD = user, password
        drools.KIE_SERVER_CONTAINER_ID = container
        drools.KIE_SERVER_CONTAINER_PACKAGE = PACKAGE
        drools.KIE_SESSION_NAME = "pifaSession"
        drools.reset_commands()
        try:
            for i, m in enumerate(models):
                d = m["demand"]
                fact = Model(f"m{i}", m["product"], int(m["inventory"]), sharing, int(baseline_pct),
                             *(int(d.get(r, 0)) for r in REGIONS))
                cmd = insert_command(object=fact, out_identifier=f"model__{i}")
                cmd.object = {f"{PACKAGE}.Model": fact}  # the KIE Server wants the fully qualified type name
                drools.add_command(cmd.initialize())
            out = drools.execute_commands()
        except drools_error as e:
            raise RulesEngineError(f"Drools KIE Server error: {e}") from e
        except Exception as e:  # noqa: BLE001 - network errors, bad JSON, missing container
            raise RulesEngineError(f"Drools KIE Server unreachable: {e}") from e
        finally:
            drools.reset_commands()
    results = {r["id"]: r for r in out.get("model", [])}
    try:
        return [{"North": results[f"m{i}"]["northAlloc"], "East": results[f"m{i}"]["eastAlloc"],
                 "West": results[f"m{i}"]["westAlloc"], "South": results[f"m{i}"]["southAlloc"],
                 "rule": results[f"m{i}"]["ruleApplied"]} for i in range(len(models))]
    except KeyError as e:
        raise RulesEngineError(f"Drools KIE Server returned an incomplete result: missing {e}") from e
