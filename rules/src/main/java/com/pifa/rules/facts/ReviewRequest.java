package com.pifa.rules.facts;

import com.fasterxml.jackson.annotation.JsonIgnore;

/** Regional Manager review decision on a regional forecast. */
public class ReviewRequest {
    private String actorRole;
    private String decision;
    private String comment;

    public ReviewRequest() {
    }

    public ReviewRequest(String actorRole, String decision, String comment) {
        this.actorRole = actorRole;
        this.decision = decision;
        this.comment = comment;
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

    @JsonIgnore
    public boolean isDecisionValid() {
        return "APPROVE".equals(decision) || "REJECT".equals(decision);
    }

    @JsonIgnore
    public boolean isCommentBlank() {
        return Checks.isBlank(comment);
    }
}
