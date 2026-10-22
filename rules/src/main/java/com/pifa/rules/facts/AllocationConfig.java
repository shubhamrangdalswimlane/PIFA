package com.pifa.rules.facts;

/** Allocation request mode plus the configurable R-ALLOC-01 parameters (from rule_config). */
public class AllocationConfig {
    public static final String UNMET_DEMAND = "UNMET_DEMAND";
    public static final String PROPORTIONAL = "PROPORTIONAL";

    private String mode;
    private double baselinePct = 25;
    private String sharing = UNMET_DEMAND;

    public AllocationConfig() {
    }

    public AllocationConfig(String mode, double baselinePct, String sharing) {
        this.mode = mode;
        this.baselinePct = baselinePct;
        this.sharing = sharing;
    }

    public String getMode() {
        return mode;
    }

    public void setMode(String mode) {
        this.mode = mode;
    }

    public double getBaselinePct() {
        return baselinePct;
    }

    public void setBaselinePct(double baselinePct) {
        this.baselinePct = baselinePct;
    }

    public String getSharing() {
        return sharing;
    }

    public void setSharing(String sharing) {
        this.sharing = sharing;
    }
}
