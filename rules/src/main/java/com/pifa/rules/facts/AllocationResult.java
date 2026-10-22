package com.pifa.rules.facts;

import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.annotation.JsonPropertyOrder;

/** One allocated quantity, serialised as {"product", "region", "qty"}. */
@JsonPropertyOrder({"product", "region", "qty"})
public class AllocationResult {
    private final int modelIndex;
    private final String product;
    private final String region;
    private final long qty;

    public AllocationResult(int modelIndex, String product, String region, long qty) {
        this.modelIndex = modelIndex;
        this.product = product;
        this.region = region;
        this.qty = qty;
    }

    @JsonIgnore
    public int getModelIndex() {
        return modelIndex;
    }

    public String getProduct() {
        return product;
    }

    public String getRegion() {
        return region;
    }

    public long getQty() {
        return qty;
    }

    @Override
    public String toString() {
        return product + "/" + region + "=" + qty;
    }
}
