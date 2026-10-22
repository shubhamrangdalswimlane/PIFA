package com.pifa.rules.facts;

/** Per-model sum of regional allocations versus available inventory (R-ALLOC-02). */
public class ModelTotals {
    private final String product;
    private final double allocated;
    private final double inventory;

    public ModelTotals(String product, double allocated, double inventory) {
        this.product = product;
        this.allocated = allocated;
        this.inventory = inventory;
    }

    public String getProduct() {
        return product;
    }

    public double getAllocated() {
        return allocated;
    }

    public double getInventory() {
        return inventory;
    }
}
