package com.pifa.rules.facts;

import com.fasterxml.jackson.annotation.JsonIgnore;

import java.util.LinkedHashMap;
import java.util.Map;

/** One printer model in an allocation request: inventory, regional demand and (for VALIDATE) allocation. */
public class ModelDemand {
    private int index;
    private String product;
    private Double inventory;
    private Map<String, Double> demand = new LinkedHashMap<>();
    private Map<String, Double> allocated = new LinkedHashMap<>();

    public ModelDemand() {
    }

    public ModelDemand(String product, Double inventory, Map<String, Double> demand, Map<String, Double> allocated) {
        this.product = product;
        this.inventory = inventory;
        this.demand = demand == null ? new LinkedHashMap<>() : demand;
        this.allocated = allocated == null ? new LinkedHashMap<>() : allocated;
    }

    @JsonIgnore
    public int getIndex() {
        return index;
    }

    @JsonIgnore
    public void setIndex(int index) {
        this.index = index;
    }

    public String getProduct() {
        return product;
    }

    public void setProduct(String product) {
        this.product = product;
    }

    public Double getInventory() {
        return inventory;
    }

    public void setInventory(Double inventory) {
        this.inventory = inventory;
    }

    public Map<String, Double> getDemand() {
        return demand;
    }

    public void setDemand(Map<String, Double> demand) {
        this.demand = demand == null ? new LinkedHashMap<>() : demand;
    }

    public Map<String, Double> getAllocated() {
        return allocated;
    }

    public void setAllocated(Map<String, Double> allocated) {
        this.allocated = allocated == null ? new LinkedHashMap<>() : allocated;
    }

    /** Demand value for a region; a missing region means 0. */
    public Double demandOf(String region) {
        Double d = demand.get(region);
        return d == null ? Double.valueOf(0) : d;
    }

    /** True when inventory and every demand value are whole numbers >= 0 (R-ALLOC-01 can run). */
    @JsonIgnore
    public boolean isInputsValid() {
        if (!Checks.isWholeNonNegative(inventory)) {
            return false;
        }
        for (String r : Checks.REGIONS) {
            if (!Checks.isWholeNonNegative(demandOf(r))) {
                return false;
            }
        }
        return true;
    }
}
