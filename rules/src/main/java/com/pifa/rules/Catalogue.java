package com.pifa.rules;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.annotation.JsonPropertyOrder;

import java.util.List;

/** Rule catalogue served at GET /rules/catalogue (Admin screen). */
public final class Catalogue {

    @JsonPropertyOrder({"id", "package", "description"})
    public record Entry(String id, @JsonProperty("package") String packageName, String description) {
    }

    public static final List<Entry> RULES = List.of(
            new Entry("R-FC-01", "forecast",
                    "Forecast, inventory and allocation quantities must be whole numbers greater than or equal to 0."),
            new Entry("R-FC-02", "forecast",
                    "Every forecast change needs a comment, and a Regional Manager revision needs a reason."),
            new Entry("R-FC-03", "forecast",
                    "A Regional Manager may approve or reject a regional forecast, and a rejection needs a comment."),
            new Entry("R-ALLOC-01", "allocation",
                    "If demand fits inventory allocate the demand, otherwise give each region a configurable baseline "
                            + "(default 25%, capped at demand) and share the rest by unmet demand."),
            new Entry("R-ALLOC-02", "allocation",
                    "The sum of regional allocations per model must not exceed available inventory."),
            new Entry("R-XFER-01", "transfer",
                    "A transfer moves a whole, positive quantity between two different valid regions, "
                            + "not more than the source allocation, and needs a comment."),
            new Entry("R-XFER-02", "approval",
                    "Allocations and transfers can only be published by approval at stage 5 (Final approval)."),
            new Entry("R-APPR-01", "approval",
                    "Only the Head of Sales can approve or reject the final allocation, and a rejection needs a comment.")
    );

    private Catalogue() {
    }
}
