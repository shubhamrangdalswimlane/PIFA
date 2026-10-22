package com.pifa.rules.facts;

import com.fasterxml.jackson.annotation.JsonIgnore;

/** Regional Manager transfer of units between two regions (stage 4). */
public class TransferRequest {
    private String product;
    private String fromRegion;
    private String toRegion;
    private Double qty;
    private Double sourceQty;
    private String comment;

    public TransferRequest() {
    }

    public TransferRequest(String product, String fromRegion, String toRegion, Double qty, Double sourceQty, String comment) {
        this.product = product;
        this.fromRegion = fromRegion;
        this.toRegion = toRegion;
        this.qty = qty;
        this.sourceQty = sourceQty;
        this.comment = comment;
    }

    public String getProduct() {
        return product;
    }

    public void setProduct(String product) {
        this.product = product;
    }

    public String getFromRegion() {
        return fromRegion;
    }

    public void setFromRegion(String fromRegion) {
        this.fromRegion = fromRegion;
    }

    public String getToRegion() {
        return toRegion;
    }

    public void setToRegion(String toRegion) {
        this.toRegion = toRegion;
    }

    public Double getQty() {
        return qty;
    }

    public void setQty(Double qty) {
        this.qty = qty;
    }

    public Double getSourceQty() {
        return sourceQty;
    }

    public void setSourceQty(Double sourceQty) {
        this.sourceQty = sourceQty;
    }

    public String getComment() {
        return comment;
    }

    public void setComment(String comment) {
        this.comment = comment;
    }

    @JsonIgnore
    public boolean isRegionsValid() {
        return Checks.isValidRegion(fromRegion) && Checks.isValidRegion(toRegion);
    }

    @JsonIgnore
    public boolean isSameRegion() {
        return fromRegion != null && fromRegion.equals(toRegion);
    }

    /** qty must be a whole number strictly greater than 0. */
    @JsonIgnore
    public boolean isQtyValid() {
        return Checks.isWholeNonNegative(qty) && qty > 0;
    }

    @JsonIgnore
    public boolean isExceedsSource() {
        return qty != null && (sourceQty == null || qty > sourceQty);
    }

    @JsonIgnore
    public boolean isCommentBlank() {
        return Checks.isBlank(comment);
    }

    /** Region to report on a violation: the source region when it is valid. */
    @JsonIgnore
    public String getReportRegion() {
        return Checks.isValidRegion(fromRegion) ? fromRegion : null;
    }
}
