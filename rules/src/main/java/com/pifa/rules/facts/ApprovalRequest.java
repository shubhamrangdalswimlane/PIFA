package com.pifa.rules.facts;

import com.fasterxml.jackson.annotation.JsonIgnore;

/** Head of Sales final decision on the allocation (stage 5). */
public class ApprovalRequest {
    private String actorRole;
    private String decision;
    private String comment;
    private Integer stage;

    public ApprovalRequest() {
    }

    public ApprovalRequest(String actorRole, String decision, String comment, Integer stage) {
        this.actorRole = actorRole;
        this.decision = decision;
        this.comment = comment;
        this.stage = stage;
    }

    public String getActorRole() {
        return actorRole;
    }

    public void setActorRole(String actorRole) {
        this.actorRole = actorRole;
    }

    public String getDecision() {
        return decision;
    }

    public void setDecision(String decision) {
        this.decision = decision;
    }

    public String getComment() {
        return comment;
    }

    public void setComment(String comment) {
        this.comment = comment;
    }

    public Integer getStage() {
        return stage;
    }

    public void setStage(Integer stage) {
        this.stage = stage;
    }

    @JsonIgnore
    public boolean isHeadOfSales() {
        return "HEAD_OF_SALES".equals(actorRole);
    }

    @JsonIgnore
    public boolean isDecisionValid() {
        return "APPROVE".equals(decision) || "REJECT".equals(decision);
    }

    @JsonIgnore
    public boolean isFinalApprovalStage() {
        return stage != null && stage == 5;
    }

    @JsonIgnore
    public boolean isCommentBlank() {
        return Checks.isBlank(comment);
    }
}
