package com.pifa.rules.facts;

import com.fasterxml.jackson.annotation.JsonPropertyOrder;

/** Rule violation, serialised as {"ruleId", "product", "region", "message"}. */
@JsonPropertyOrder({"ruleId", "product", "region", "message"})
public class Violation {
    private String ruleId;
    private String product;
    private String region;
    private String message;

    public Violation() {
    }

    public Violation(String ruleId, String product, String region, String message) {
        this.ruleId = ruleId;
        this.product = product;
        this.region = region;
        this.message = message;
    }

    public String getRuleId() {
        return ruleId;
    }

    public String getProduct() {
        return product;
    }

    public String getRegion() {
        return region;
    }

    public String getMessage() {
        return message;
    }

    public void setRuleId(String ruleId) {
        this.ruleId = ruleId;
    }

    public void setProduct(String product) {
        this.product = product;
    }

    public void setRegion(String region) {
        this.region = region;
    }

    public void setMessage(String message) {
        this.message = message;
    }

    @Override
    public String toString() {
        return ruleId + "[" + product + "/" + region + "]: " + message;
    }
}
