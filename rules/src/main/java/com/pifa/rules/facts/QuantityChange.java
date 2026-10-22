package com.pifa.rules.facts;

import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.annotation.JsonProperty;

/** One edited quantity (forecast, inventory or allocation) with its comment. */
public class QuantityChange {
    private String entity;
    private String product;
    private String region;
    private Double qty;
    private String comment;
    @JsonProperty("isRevision")
    private boolean revision;

    public QuantityChange() {
    }

    public QuantityChange(String entity, String product, String region, Double qty, String comment, boolean revision) {
        this.entity = entity;
        this.product = product;
        this.region = region;
        this.qty = qty;
        this.comment = comment;
        this.revision = revision;
    }

    public String getEntity() {
        return entity;
    }

    public void setEntity(String entity) {
        this.entity = entity;
    }

    public String getProduct() {
        return product;
    }

    public void setProduct(String product) {
        this.product = product;
    }

    public String getRegion() {
        return region;
    }

    public void setRegion(String region) {
        this.region = region;
    }

    public Double getQty() {
        return qty;
    }

    public void setQty(Double qty) {
        this.qty = qty;
    }

    public String getComment() {
        return comment;
    }

    public void setComment(String comment) {
        this.comment = comment;
    }

    @JsonProperty("isRevision")
    public boolean isRevision() {
        return revision;
    }

    @JsonProperty("isRevision")
    public void setRevision(boolean revision) {
        this.revision = revision;
    }

    @JsonIgnore
    public boolean isQtyValid() {
        return Checks.isWholeNonNegative(qty);
    }

    @JsonIgnore
    public boolean isCommentBlank() {
        return Checks.isBlank(comment);
    }
}
