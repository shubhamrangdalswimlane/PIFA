package com.pifa.rules;

/** HTTP error rendered as {"detail": "..."}. */
public class ApiError extends RuntimeException {
    private final int status;

    public ApiError(int status, String detail) {
        super(detail);
        this.status = status;
    }

    public int getStatus() {
        return status;
    }
}
