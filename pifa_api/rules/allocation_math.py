"""R-ALLOC-01 arithmetic.

- Total demand <= inventory: every region gets its demand; surplus stays unallocated.
- UNMET_DEMAND: baseline floor(inventory * pct / 100) per region, capped at that region's demand; the
  remainder is shared in proportion to unmet demand with largest-remainder rounding (ties broken in
  region order North, East, West, South), never above demand.
- PROPORTIONAL: inventory shared in proportion to demand with largest-remainder rounding.

When stock is constrained the allocated total always equals the inventory exactly.
"""

import math

REGIONS = ["North", "East", "West", "South"]
UNMET_DEMAND = "UNMET_DEMAND"
PROPORTIONAL = "PROPORTIONAL"


def allocate(inventory: int, demand: dict[str, int], baseline_pct: float, sharing: str) -> dict[str, int]:
    """Allocation per region (in region order) for one printer model.

    Args:
        inventory: available units of the model.
        demand: forecast demand per region (missing regions count as 0).
        baseline_pct: baseline share per region, in percent of inventory (UNMET_DEMAND sharing only).
        sharing: UNMET_DEMAND or PROPORTIONAL.

    Returns:
        {region: allocated units} in region order North, East, West, South.

    Raises:
        ValueError: when the inventory or any demand is negative.
    """
    d = [int(demand.get(r, 0)) for r in REGIONS]
    if inventory < 0 or any(x < 0 for x in d):
        raise ValueError("inventory and demand must be >= 0")

    if sum(d) <= inventory:
        alloc = d
    elif sharing == PROPORTIONAL:
        alloc = largest_remainder(inventory, d)
    else:
        base = math.floor(inventory * baseline_pct / 100)
        baseline = [min(base, x) for x in d]
        if sum(baseline) > inventory:
            # Only possible when baselinePct > 25: shrink the baselines proportionally to fit.
            alloc = largest_remainder(inventory, baseline)
        else:
            unmet = [x - b for x, b in zip(d, baseline, strict=True)]
            extra = largest_remainder(inventory - sum(baseline), unmet)
            alloc = [b + e for b, e in zip(baseline, extra, strict=True)]
    return dict(zip(REGIONS, alloc, strict=True))


def largest_remainder(units: int, weights: list[int]) -> list[int]:
    """Share `units` in proportion to `weights` (Hamilton method), exact integer arithmetic.

    Requires units <= sum(weights), which guarantees no share exceeds its weight.
    Ties on the remainder go to the earlier region in region order.

    Args:
        units: whole units to share.
        weights: weight per region, in region order.

    Returns:
        Integer shares in the same order as `weights`, summing to `units`.

    Raises:
        ValueError: when `units` exceeds the total weight.
    """
    total = sum(weights)
    if units <= 0 or total == 0:
        return [0] * len(weights)
    if units > total:
        raise ValueError("units exceed total weight")
    share = [units * w // total for w in weights]
    remainder = [units * w % total for w in weights]
    left = units - sum(share)
    for i in sorted(range(len(weights)), key=lambda i: (-remainder[i], i)):
        if left == 0:
            break
        if remainder[i] > 0 and share[i] < weights[i]:
            share[i] += 1
            left -= 1
    if left:
        raise ArithmeticError("largest remainder did not distribute all units")
    return share
