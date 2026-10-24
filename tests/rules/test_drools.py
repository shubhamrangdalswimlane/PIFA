"""Allocation through Drools: the worked example, the python-drools-sdk request, and the Python/Drools switch."""

import pytest

from pifa_api.config import get_settings
from pifa_api.rules import RulesEngineError, drools_client, evaluate, self_test

EXAMPLE = {"product": "P", "inventory": 50, "demand": {"North": 30, "South": 25, "East": 20, "West": 25}}


def alloc(model, sharing="PROPORTIONAL", pct=25):
    result = evaluate("allocation", {"mode": "ALLOCATE", "config": {"baselinePct": pct, "sharing": sharing}, "models": [model]})
    return {a["region"]: a["qty"] for a in result["allocations"]}


def test_equal_percentage_cut_example():
    # Forecast 30/25/20/25 with 50 in stock: every region gets 50% -> North 15, South 12, East 10, West 13.
    assert alloc(EXAMPLE) == {"North": 15, "East": 10, "West": 13, "South": 12}


def test_forecast_that_fits_is_allocated_exactly():
    assert alloc({**EXAMPLE, "inventory": 120}) == {"North": 30, "East": 20, "West": 25, "South": 25}


def test_self_test_uses_the_example():
    assert self_test()[0]


class FakeKie:
    """Stands in for python-drools-sdk's HTTP call and answers like allocation.drl would."""

    def __init__(self):
        self.commands = None

    def execute(self):
        from python_drools_sdk.kie.drools import Drools

        self.commands = list(Drools.commands)
        facts = [c["insert"].object[f"{drools_client.PACKAGE}.Model"] for c in self.commands]
        return {"model": [{"id": f.id, "northAlloc": 1, "eastAlloc": 2, "westAlloc": 3, "southAlloc": 4, "ruleApplied": "TEST"} for f in facts]}


@pytest.fixture()
def kie(monkeypatch):
    from python_drools_sdk.kie.drools import Drools

    fake = FakeKie()
    monkeypatch.setattr(Drools, "execute_commands", classmethod(lambda cls: fake.execute()))
    return fake


def test_drools_request_built_with_the_sdk(kie):
    out = drools_client.allocate([EXAMPLE], "PROPORTIONAL", 25, "http://kie:8080/", "pifa", "pw", "pifa")
    assert out == [{"North": 1, "East": 2, "West": 3, "South": 4, "rule": "TEST"}]
    fact = kie.commands[0]["insert"].object[f"{drools_client.PACKAGE}.Model"]
    assert (fact.inventory, fact.northDemand, fact.southDemand, fact.sharing) == (50, 30, 25, "PROPORTIONAL")
    from python_drools_sdk.kie.drools import Drools

    assert Drools.KIE_SERVER_ROOT_URL == "http://kie:8080" and Drools.commands == []


def test_evaluate_uses_drools_when_configured(kie, monkeypatch):
    monkeypatch.setattr(get_settings(), "drools_url", "http://kie:8080")
    assert alloc(EXAMPLE) == {"North": 1, "East": 2, "West": 3, "South": 4}


def test_drools_failure_is_reported_not_hidden(monkeypatch):
    monkeypatch.setattr(get_settings(), "drools_url", "http://127.0.0.1:9")
    with pytest.raises(RulesEngineError):
        alloc(EXAMPLE)
