package com.pifa.rules;

import com.pifa.rules.facts.AllocationConfig;
import com.pifa.rules.facts.AllocationResult;
import com.pifa.rules.facts.Checks;
import com.pifa.rules.facts.ModelDemand;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * R-ALLOC-01 arithmetic, kept in plain Java so it is unit-testable. Called from the DRL rule RHS.
 *
 * <ul>
 *   <li>Total demand &lt;= inventory: every region gets its demand; surplus stays unallocated.</li>
 *   <li>UNMET_DEMAND: baseline floor(inventory * pct / 100) per region, capped at that region's demand;
 *       the remainder is shared in proportion to unmet demand with largest-remainder rounding
 *       (ties broken in region order North, East, West, South), never above demand.</li>
 *   <li>PROPORTIONAL: inventory shared in proportion to demand with largest-remainder rounding.</li>
 * </ul>
 * When constrained the allocated total always equals the inventory exactly.
 */
public final class AllocationMath {

    private AllocationMath() {
    }

    /** Allocates one model and returns one result per region in region order. */
    public static List<AllocationResult> allocateModel(ModelDemand m, AllocationConfig cfg) {
        Map<String, Long> demand = new LinkedHashMap<>();
        for (String r : Checks.REGIONS) {
            demand.put(r, m.demandOf(r).longValue());
        }
        Map<String, Long> out = allocate(m.getInventory().longValue(), demand, cfg.getBaselinePct(), cfg.getSharing());
        List<AllocationResult> results = new ArrayList<>();
        for (String r : Checks.REGIONS) {
            results.add(new AllocationResult(m.getIndex(), m.getProduct(), r, out.get(r)));
        }
        return results;
    }

    /**
     * @param inventory   available units (>= 0)
     * @param demand      demand per region (missing region = 0, values >= 0)
     * @param baselinePct baseline percentage of inventory per region (0..100), UNMET_DEMAND only
     * @param sharing     {@link AllocationConfig#UNMET_DEMAND} or {@link AllocationConfig#PROPORTIONAL}
     * @return allocation per region, in region order
     */
    public static Map<String, Long> allocate(long inventory, Map<String, Long> demand, double baselinePct, String sharing) {
        long[] d = new long[Checks.REGIONS.size()];
        long totalDemand = 0;
        for (int i = 0; i < d.length; i++) {
            Long v = demand.get(Checks.REGIONS.get(i));
            d[i] = v == null ? 0 : v;
            if (d[i] < 0) {
                throw new IllegalArgumentException("demand must be >= 0");
            }
            totalDemand += d[i];
        }
        if (inventory < 0) {
            throw new IllegalArgumentException("inventory must be >= 0");
        }

        long[] alloc;
        if (totalDemand <= inventory) {
            alloc = d.clone();
        } else if (AllocationConfig.PROPORTIONAL.equals(sharing)) {
            alloc = largestRemainder(inventory, d);
        } else {
            long base = (long) Math.floor(inventory * baselinePct / 100.0);
            long[] baseline = new long[d.length];
            long baselineSum = 0;
            for (int i = 0; i < d.length; i++) {
                baseline[i] = Math.min(base, d[i]);
                baselineSum += baseline[i];
            }
            if (baselineSum > inventory) {
                // Only possible when baselinePct > 25: shrink the baselines proportionally to fit.
                alloc = largestRemainder(inventory, baseline);
            } else {
                long[] unmet = new long[d.length];
                for (int i = 0; i < d.length; i++) {
                    unmet[i] = d[i] - baseline[i];
                }
                long[] extra = largestRemainder(inventory - baselineSum, unmet);
                alloc = new long[d.length];
                for (int i = 0; i < d.length; i++) {
                    alloc[i] = baseline[i] + extra[i];
                }
            }
        }

        Map<String, Long> out = new LinkedHashMap<>();
        for (int i = 0; i < d.length; i++) {
            out.put(Checks.REGIONS.get(i), alloc[i]);
        }
        return out;
    }

    /**
     * Shares {@code units} in proportion to {@code weights} (Hamilton / largest-remainder method).
     * Requires units &lt;= sum(weights), which guarantees no share exceeds its weight.
     * Ties on the remainder go to the earlier region in region order.
     */
    static long[] largestRemainder(long units, long[] weights) {
        long total = 0;
        for (long w : weights) {
            total += w;
        }
        long[] share = new long[weights.length];
        if (units <= 0 || total == 0) {
            return share;
        }
        if (units > total) {
            throw new IllegalArgumentException("units exceed total weight");
        }
        long[] remainder = new long[weights.length];
        long given = 0;
        for (int i = 0; i < weights.length; i++) {
            // Exact integer arithmetic: share = floor(units * w / total), remainder = (units * w) mod total.
            java.math.BigInteger p = java.math.BigInteger.valueOf(units).multiply(java.math.BigInteger.valueOf(weights[i]));
            java.math.BigInteger[] qr = p.divideAndRemainder(java.math.BigInteger.valueOf(total));
            share[i] = qr[0].longValueExact();
            remainder[i] = qr[1].longValueExact();
            given += share[i];
        }
        long left = units - given;
        List<Integer> order = new ArrayList<>();
        for (int i = 0; i < weights.length; i++) {
            order.add(i);
        }
        order.sort(Comparator.<Integer>comparingLong(i -> -remainder[i]).thenComparingInt(i -> i));
        for (int k = 0; k < order.size() && left > 0; k++) {
            int i = order.get(k);
            if (remainder[i] > 0 && share[i] < weights[i]) {
                share[i]++;
                left--;
            }
        }
        if (left != 0) {
            throw new IllegalStateException("largest remainder did not distribute all units");
        }
        return share;
    }
}
