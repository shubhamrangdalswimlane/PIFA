package com.pifa.rules.facts;

import java.util.List;

/** Small, pure helpers shared by fact classes and DRL right-hand sides. */
public final class Checks {

    /** Fixed region order used everywhere (ties, output order). */
    public static final List<String> REGIONS = List.of("North", "East", "West", "South");

    private Checks() {
    }

    public static boolean isBlank(String s) {
        return s == null || s.trim().isEmpty();
    }

    public static boolean isWholeNonNegative(Double d) {
        return d != null && !d.isNaN() && !d.isInfinite() && d >= 0 && d == Math.floor(d);
    }

    public static boolean isValidRegion(String region) {
        return region != null && REGIONS.contains(region);
    }

    public static int regionIndex(String region) {
        int i = region == null ? -1 : REGIONS.indexOf(region);
        return i < 0 ? REGIONS.size() : i;
    }

    /** Formats 12.0 as "12" and 2.5 as "2.5" for messages. */
    public static String fmt(Double d) {
        if (d == null) {
            return "null";
        }
        if (!d.isNaN() && !d.isInfinite() && d == Math.rint(d) && Math.abs(d) < 1e15) {
            return Long.toString(d.longValue());
        }
        return d.toString();
    }
}
