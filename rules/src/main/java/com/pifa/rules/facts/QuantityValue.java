package com.pifa.rules.facts;

/** A single quantity inside an allocation request (inventory, demand or allocated), checked by R-FC-01. */
public class QuantityValue {
    private final String product;
    private final String region;
    private final String field;
    private final Double qty;

    public QuantityValue(String product, String region, String field, Double qty) {
        this.product = product;
        this.region = region;
        this.field = field;
        this.qty = qty;
    }

    public String getProduct() {
        return product;
    }

    public String getRegion() {
        return region;
    }

    public String getField() {
        return field;
    }

    public Double getQty() {
        return qty;
    }

    public boolean isValid() {
        return Checks.isWholeNonNegative(qty);
    }
}
