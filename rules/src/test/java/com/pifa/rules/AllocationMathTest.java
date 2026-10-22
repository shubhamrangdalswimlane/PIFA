package com.pifa.rules;

import com.pifa.rules.facts.AllocationConfig;
import org.junit.jupiter.api.Test;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Random;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class AllocationMathTest {

    private static Map<String, Long> regions(long n, long e, long w, long s) {
        Map<String, Long> m = new LinkedHashMap<>();
        m.put("North", n);
        m.put("East", e);
        m.put("West", w);
        m.put("South", s);
        return m;
    }

    private static long sum(Map<String, Long> m) {
        return m.values().stream().mapToLong(Long::longValue).sum();
    }

    @Test
    void prdWorkedExampleAllocatesDemandWhenItFits() {
        // PRD: Model A, inventory 100, demand 25 each -> 25/25/25/25.
        Map<String, Long> out = AllocationMath.allocate(100, regions(25, 25, 25, 25), 25, AllocationConfig.UNMET_DEMAND);
        assertEquals(regions(25, 25, 25, 25), out);
    }

    @Test
    void unconstrainedLeavesSurplusUnallocated() {
        Map<String, Long> out = AllocationMath.allocate(100, regions(10, 20, 30, 5), 25, AllocationConfig.UNMET_DEMAND);
        assertEquals(regions(10, 20, 30, 5), out);
        assertEquals(65, sum(out));
    }

    @Test
    void constrainedBaselineThenUnmetDemand() {
        // Baseline floor(100*25%)=25 capped at demand -> 25/25/20/0 (70); remainder 30 by unmet 35/15/0/0 -> 21/9.
        Map<String, Long> out = AllocationMath.allocate(100, regions(60, 40, 20, 0), 25, AllocationConfig.UNMET_DEMAND);
        assertEquals(regions(46, 34, 20, 0), out);
        assertEquals(100, sum(out));
    }

    @Test
    void roundingTieBrokenInRegionOrder() {
        // Baseline 2 each (8), remainder 2, unmet 8 each -> exact share 0.5 each; ties go North, East.
        Map<String, Long> out = AllocationMath.allocate(10, regions(10, 10, 10, 10), 25, AllocationConfig.UNMET_DEMAND);
        assertEquals(regions(3, 3, 2, 2), out);
        assertEquals(10, sum(out));
    }

    @Test
    void roundingLargestRemainderWins() {
        // Baseline 1 each (cap: South demand 1); remainder 3 shared by unmet 9/5/2/0 (total 16):
        // exact 1.6875 / 0.9375 / 0.375 -> floors 1/0/0, two leftovers to East (.9375) and North (.6875), not West.
        Map<String, Long> out = AllocationMath.allocate(7, regions(10, 6, 3, 1), 25, AllocationConfig.UNMET_DEMAND);
        assertEquals(regions(3, 2, 1, 1), out);
        assertEquals(7, sum(out));
    }

    @Test
    void proportionalMode() {
        // 100 * 60/120 = 50, 100 * 40/120 = 33.33, 100 * 20/120 = 16.67 -> 50/33/17/0.
        Map<String, Long> out = AllocationMath.allocate(100, regions(60, 40, 20, 0), 25, AllocationConfig.PROPORTIONAL);
        assertEquals(regions(50, 33, 17, 0), out);
    }

    @Test
    void baselineAboveQuarterStillFitsInventory() {
        Map<String, Long> out = AllocationMath.allocate(10, regions(10, 10, 10, 10), 40, AllocationConfig.UNMET_DEMAND);
        assertEquals(10, sum(out));
        assertEquals(regions(3, 3, 2, 2), out);
    }

    @Test
    void zeroInventoryAllocatesNothing() {
        assertEquals(regions(0, 0, 0, 0), AllocationMath.allocate(0, regions(5, 5, 5, 5), 25, AllocationConfig.UNMET_DEMAND));
    }

    @Test
    void randomisedInvariants() {
        Random rnd = new Random(42);
        for (int i = 0; i < 5000; i++) {
            Map<String, Long> d = regions(rnd.nextInt(200), rnd.nextInt(200), rnd.nextInt(200), rnd.nextInt(200));
            long inv = rnd.nextInt(500);
            double pct = rnd.nextInt(101);
            String sharing = rnd.nextBoolean() ? AllocationConfig.UNMET_DEMAND : AllocationConfig.PROPORTIONAL;
            Map<String, Long> out = AllocationMath.allocate(inv, d, pct, sharing);
            long demand = sum(d);
            assertEquals(Math.min(inv, demand), sum(out), "total for " + d + " inv " + inv);
            for (String r : d.keySet()) {
                assertTrue(out.get(r) >= 0 && out.get(r) <= d.get(r), "region " + r + " within demand");
            }
        }
    }
}
