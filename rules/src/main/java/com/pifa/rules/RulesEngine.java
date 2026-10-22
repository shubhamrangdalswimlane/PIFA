package com.pifa.rules;

import com.pifa.rules.facts.AllocationConfig;
import com.pifa.rules.facts.AllocationResult;
import com.pifa.rules.facts.ApprovalRequest;
import com.pifa.rules.facts.Checks;
import com.pifa.rules.facts.ModelDemand;
import com.pifa.rules.facts.ModelTotals;
import com.pifa.rules.facts.QuantityChange;
import com.pifa.rules.facts.QuantityValue;
import com.pifa.rules.facts.ReviewRequest;
import com.pifa.rules.facts.TransferRequest;
import com.pifa.rules.facts.Violation;
import org.kie.api.KieBase;
import org.kie.api.KieServices;
import org.kie.api.builder.KieBuilder;
import org.kie.api.builder.KieFileSystem;
import org.kie.api.builder.Message;
import org.kie.api.builder.ReleaseId;
import org.kie.api.runtime.KieContainer;
import org.kie.api.runtime.KieSession;

import java.io.IOException;
import java.io.InputStream;
import java.io.UncheckedIOException;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Builds one KieBase per rule package (forecast, allocation, transfer, approval) from the DRL files on the
 * classpath and evaluates requests in a fresh stateful session each time. Thread-safe.
 */
public class RulesEngine {

    public static final List<String> PACKAGES = List.of("forecast", "allocation", "transfer", "approval");

    private final Map<String, KieBase> bases = new LinkedHashMap<>();

    public RulesEngine() {
        for (String pkg : PACKAGES) {
            bases.put(pkg, build(pkg));
        }
    }

    private static KieBase build(String pkg) {
        KieServices ks = KieServices.Factory.get();
        KieFileSystem kfs = ks.newKieFileSystem();
        ReleaseId releaseId = ks.newReleaseId("com.pifa", "pifa-rules-" + pkg, "1.0.0");
        kfs.generateAndWritePomXML(releaseId);
        String path = "rules/" + pkg + "/" + pkg + ".drl";
        kfs.write("src/main/resources/" + path, ks.getResources().newByteArrayResource(readResource(path)));
        KieBuilder builder = ks.newKieBuilder(kfs).buildAll();
        if (builder.getResults().hasMessages(Message.Level.ERROR)) {
            throw new IllegalStateException("DRL errors in " + path + ": " + builder.getResults().getMessages());
        }
        KieContainer container = ks.newKieContainer(releaseId);
        return container.getKieBase();
    }

    private static byte[] readResource(String path) {
        try (InputStream in = RulesEngine.class.getClassLoader().getResourceAsStream(path)) {
            if (in == null) {
                throw new IllegalStateException("Missing rule file on classpath: " + path);
            }
            return in.readAllBytes();
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }

    /** Result of an allocation evaluation. */
    public record AllocationOutcome(List<AllocationResult> allocations, List<Violation> violations) {
    }

    /** R-FC-01, R-FC-02, R-FC-03. */
    public List<Violation> evaluateForecast(List<QuantityChange> changes, ReviewRequest review) {
        List<Object> facts = new ArrayList<>();
        if (changes != null) {
            changes.stream().filter(c -> c != null).forEach(facts::add);
        }
        if (review != null) {
            facts.add(review);
        }
        return run("forecast", facts, null);
    }

    /** ALLOCATE: R-ALLOC-01 (+ R-FC-01 on inputs). VALIDATE: R-ALLOC-02 + R-FC-01. */
    public AllocationOutcome evaluateAllocation(AllocationConfig config, List<ModelDemand> models) {
        boolean allocate = "ALLOCATE".equals(config.getMode());
        List<Object> facts = new ArrayList<>();
        facts.add(config);
        int idx = 0;
        for (ModelDemand m : models) {
            m.setIndex(idx++);
            facts.add(m);
            facts.add(new QuantityValue(m.getProduct(), null, "inventory", m.getInventory()));
            Map<String, Double> values = allocate ? m.getDemand() : m.getAllocated();
            String field = allocate ? "demand" : "allocated";
            double sum = 0;
            for (String r : Checks.REGIONS) {
                if (values.containsKey(r)) {
                    Double v = values.get(r);
                    facts.add(new QuantityValue(m.getProduct(), r, field, v));
                    sum += v == null ? 0 : v;
                }
            }
            if (!allocate) {
                double inv = m.getInventory() == null ? 0 : m.getInventory();
                facts.add(new ModelTotals(m.getProduct(), sum, inv));
            }
        }
        List<AllocationResult> allocations = new ArrayList<>();
        List<Violation> violations = run("allocation", facts, allocations);
        allocations.sort(Comparator.comparingInt(AllocationResult::getModelIndex)
                .thenComparingInt(a -> Checks.regionIndex(a.getRegion())));
        return new AllocationOutcome(allocations, violations);
    }

    /** R-XFER-01. */
    public List<Violation> evaluateTransfer(TransferRequest transfer) {
        return run("transfer", List.of(transfer), null);
    }

    /** R-APPR-01, R-XFER-02. */
    public List<Violation> evaluateApproval(ApprovalRequest request) {
        return run("approval", List.of(request), null);
    }

    private List<Violation> run(String pkg, List<?> facts, List<AllocationResult> allocations) {
        List<Violation> violations = new ArrayList<>();
        KieSession session = bases.get(pkg).newKieSession();
        try {
            session.setGlobal("violations", violations);
            if (allocations != null) {
                session.setGlobal("allocations", allocations);
            }
            for (Object f : facts) {
                session.insert(f);
            }
            session.fireAllRules();
        } finally {
            session.dispose();
        }
        // Deterministic output order regardless of rule firing order.
        violations.sort(Comparator.comparing(Violation::getRuleId)
                .thenComparing(v -> v.getProduct() == null ? "" : v.getProduct())
                .thenComparingInt(v -> Checks.regionIndex(v.getRegion()))
                .thenComparing(Violation::getMessage));
        return violations;
    }
}
