package com.pifa.rules;

import com.pifa.rules.facts.AllocationConfig;
import com.pifa.rules.facts.AllocationResult;
import com.pifa.rules.facts.ApprovalRequest;
import com.pifa.rules.facts.ModelDemand;
import com.pifa.rules.facts.QuantityChange;
import com.pifa.rules.facts.ReviewRequest;
import com.pifa.rules.facts.TransferRequest;
import com.pifa.rules.facts.Violation;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** A passing and a failing case for every rule ID, run through the real DRL. */
class RulesEngineTest {

    private static RulesEngine engine;

    @BeforeAll
    static void setUp() {
        engine = new RulesEngine();
    }

    private static List<String> ids(List<Violation> vs) {
        return vs.stream().map(Violation::getRuleId).collect(Collectors.toList());
    }

    private static Map<String, Double> regions(double n, double e, double w, double s) {
        Map<String, Double> m = new LinkedHashMap<>();
        m.put("North", n);
        m.put("East", e);
        m.put("West", w);
        m.put("South", s);
        return m;
    }

    private static Map<String, Long> qtyByRegion(List<AllocationResult> rs, String product) {
        Map<String, Long> m = new LinkedHashMap<>();
        rs.stream().filter(r -> r.getProduct().equals(product)).forEach(r -> m.put(r.getRegion(), r.getQty()));
        return m;
    }

    private static QuantityChange change(Double qty, String comment, boolean revision) {
        return new QuantityChange("forecast", "Model A", "North", qty, comment, revision);
    }

    // ---- forecast package --------------------------------------------------------------------------

    @Test
    void rFc01PassesWholeNonNegative() {
        assertEquals(List.of(), engine.evaluateForecast(List.of(change(12.0, "ok", false), change(0.0, "zero", false)), null));
    }

    @Test
    void rFc01FailsFractionNegativeAndMissing() {
        List<Violation> vs = engine.evaluateForecast(
                List.of(change(2.5, "c", false), change(-1.0, "c", false), change(null, "c", false)), null);
        assertEquals(List.of("R-FC-01", "R-FC-01", "R-FC-01"), ids(vs));
        assertEquals("Model A", vs.get(0).getProduct());
        assertEquals("North", vs.get(0).getRegion());
    }

    @Test
    void rFc02PassesWithCommentAndReason() {
        assertEquals(List.of(), engine.evaluateForecast(
                List.of(change(10.0, "promo", false), change(11.0, "customer order", true)), null));
    }

    @Test
    void rFc02FailsWithoutCommentAndMentionsReasonForRevision() {
        List<Violation> plain = engine.evaluateForecast(List.of(change(10.0, "  ", false)), null);
        assertEquals(List.of("R-FC-02"), ids(plain));
        List<Violation> revision = engine.evaluateForecast(List.of(change(10.0, null, true)), null);
        assertEquals(List.of("R-FC-02"), ids(revision));
        assertTrue(revision.get(0).getMessage().toLowerCase().contains("reason"));
    }

    @Test
    void rFc03PassesApproveWithoutCommentAndRejectWithComment() {
        assertEquals(List.of(), engine.evaluateForecast(List.of(), new ReviewRequest("REGIONAL_MANAGER", "APPROVE", null)));
        assertEquals(List.of(), engine.evaluateForecast(null, new ReviewRequest("REGIONAL_MANAGER", "REJECT", "too high")));
    }

    @Test
    void rFc03FailsRejectWithoutComment() {
        assertEquals(List.of("R-FC-03"),
                ids(engine.evaluateForecast(List.of(), new ReviewRequest("REGIONAL_MANAGER", "REJECT", ""))));
    }

    // ---- allocation package ------------------------------------------------------------------------

    @Test
    void rAlloc01PrdWorkedExample() {
        ModelDemand m = new ModelDemand("Model A", 100.0, regions(25, 25, 25, 25), null);
        RulesEngine.AllocationOutcome out = engine.evaluateAllocation(
                new AllocationConfig("ALLOCATE", 25, AllocationConfig.UNMET_DEMAND), List.of(m));
        assertEquals(List.of(), out.violations());
        assertEquals(Map.of("North", 25L, "East", 25L, "West", 25L, "South", 25L), qtyByRegion(out.allocations(), "Model A"));
        assertEquals(List.of("North", "East", "West", "South"),
                out.allocations().stream().map(AllocationResult::getRegion).collect(Collectors.toList()));
    }

    @Test
    void rAlloc01ConstrainedAndMultipleModels() {
        ModelDemand a = new ModelDemand("Model A", 100.0, regions(60, 40, 20, 0), null);
        ModelDemand b = new ModelDemand("Model B", 10.0, regions(10, 10, 10, 10), null);
        RulesEngine.AllocationOutcome out = engine.evaluateAllocation(
                new AllocationConfig("ALLOCATE", 25, AllocationConfig.UNMET_DEMAND), List.of(a, b));
        assertEquals(List.of(), out.violations());
        assertEquals(Map.of("North", 46L, "East", 34L, "West", 20L, "South", 0L), qtyByRegion(out.allocations(), "Model A"));
        assertEquals(Map.of("North", 3L, "East", 3L, "West", 2L, "South", 2L), qtyByRegion(out.allocations(), "Model B"));
        assertEquals("Model A", out.allocations().get(0).getProduct());
        assertEquals(8, out.allocations().size());
    }

    @Test
    void rAlloc01FailsOnInvalidInputs() {
        ModelDemand m = new ModelDemand("Model A", 100.0, regions(25.5, 25, 25, -1), null);
        RulesEngine.AllocationOutcome out = engine.evaluateAllocation(
                new AllocationConfig("ALLOCATE", 25, AllocationConfig.UNMET_DEMAND), List.of(m));
        assertEquals(List.of(), out.allocations());
        assertEquals(List.of("R-FC-01", "R-FC-01"), ids(out.violations()));
    }

    @Test
    void rAlloc02PassesWithinInventory() {
        ModelDemand m = new ModelDemand("Model A", 100.0, null, regions(30, 20, 25, 25));
        RulesEngine.AllocationOutcome out = engine.evaluateAllocation(
                new AllocationConfig("VALIDATE", 25, AllocationConfig.UNMET_DEMAND), List.of(m));
        assertEquals(List.of(), out.violations());
        assertEquals(List.of(), out.allocations());
    }

    @Test
    void rAlloc02FailsAboveInventory() {
        ModelDemand m = new ModelDemand("Model A", 100.0, null, regions(31, 20, 25, 25));
        List<Violation> vs = engine.evaluateAllocation(
                new AllocationConfig("VALIDATE", 25, AllocationConfig.UNMET_DEMAND), List.of(m)).violations();
        assertEquals(List.of("R-ALLOC-02"), ids(vs));
        assertEquals("Model A", vs.get(0).getProduct());
        assertEquals(null, vs.get(0).getRegion());
        assertEquals("Allocated 101 exceeds inventory 100", vs.get(0).getMessage());
    }

    @Test
    void validateAlsoAppliesRFc01() {
        ModelDemand m = new ModelDemand("Model A", 100.0, null, regions(10.5, 20, 25, 25));
        List<Violation> vs = engine.evaluateAllocation(
                new AllocationConfig("VALIDATE", 25, AllocationConfig.UNMET_DEMAND), List.of(m)).violations();
        assertEquals(List.of("R-FC-01"), ids(vs));
        assertEquals("North", vs.get(0).getRegion());
    }

    // ---- transfer package --------------------------------------------------------------------------

    @Test
    void rXfer01PassesPrdTransferExample() {
        // PRD: East -> North 5 from 25/25/25/25 gives 30/20/25/25.
        assertEquals(List.of(), engine.evaluateTransfer(
                new TransferRequest("Model A", "East", "North", 5.0, 25.0, "North customer order")));
    }

    @Test
    void rXfer01FailsEachCondition() {
        assertEquals(List.of("R-XFER-01"), ids(engine.evaluateTransfer(
                new TransferRequest("Model A", "East", "East", 5.0, 25.0, "c"))));
        assertEquals(List.of("R-XFER-01"), ids(engine.evaluateTransfer(
                new TransferRequest("Model A", "East", "Central", 5.0, 25.0, "c"))));
        assertEquals(List.of("R-XFER-01"), ids(engine.evaluateTransfer(
                new TransferRequest("Model A", "East", "North", 0.0, 25.0, "c"))));
        assertEquals(List.of("R-XFER-01"), ids(engine.evaluateTransfer(
                new TransferRequest("Model A", "East", "North", 2.5, 25.0, "c"))));
        assertEquals(List.of("R-XFER-01"), ids(engine.evaluateTransfer(
                new TransferRequest("Model A", "East", "North", 26.0, 25.0, "c"))));
        assertEquals(List.of("R-XFER-01"), ids(engine.evaluateTransfer(
                new TransferRequest("Model A", "East", "North", 5.0, 25.0, " "))));
        List<Violation> vs = engine.evaluateTransfer(new TransferRequest("Model A", "East", "North", 26.0, 25.0, null));
        assertEquals(2, vs.size());
        assertEquals("East", vs.get(0).getRegion());
    }

    // ---- approval package --------------------------------------------------------------------------

    @Test
    void rAppr01PassesHeadOfSales() {
        assertEquals(List.of(), engine.evaluateApproval(new ApprovalRequest("HEAD_OF_SALES", "APPROVE", null, 5)));
        assertEquals(List.of(), engine.evaluateApproval(new ApprovalRequest("HEAD_OF_SALES", "REJECT", "rework East", 5)));
    }

    @Test
    void rAppr01FailsOtherRoleOrRejectWithoutComment() {
        assertEquals(List.of("R-APPR-01"), ids(engine.evaluateApproval(new ApprovalRequest("PLANNER", "REJECT", "x", 5))));
        assertEquals(List.of("R-APPR-01"), ids(engine.evaluateApproval(new ApprovalRequest("HEAD_OF_SALES", "REJECT", "", 5))));
        assertEquals(List.of("R-APPR-01"), ids(engine.evaluateApproval(new ApprovalRequest("HEAD_OF_SALES", "MAYBE", "x", 5))));
    }

    @Test
    void rXfer02PassesAtStage5() {
        assertEquals(List.of(), engine.evaluateApproval(new ApprovalRequest("HEAD_OF_SALES", "APPROVE", "", 5)));
    }

    @Test
    void rXfer02FailsBeforeStage5() {
        assertEquals(List.of("R-XFER-02"), ids(engine.evaluateApproval(new ApprovalRequest("HEAD_OF_SALES", "APPROVE", "", 4))));
        assertEquals(List.of("R-APPR-01", "R-XFER-02"),
                ids(engine.evaluateApproval(new ApprovalRequest("REGIONAL_MANAGER", "APPROVE", "", 4))));
    }
}
