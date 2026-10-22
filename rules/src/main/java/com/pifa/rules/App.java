package com.pifa.rules;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.pifa.rules.facts.AllocationConfig;
import com.pifa.rules.facts.ApprovalRequest;
import com.pifa.rules.facts.Checks;
import com.pifa.rules.facts.ModelDemand;
import com.pifa.rules.facts.QuantityChange;
import com.pifa.rules.facts.ReviewRequest;
import com.pifa.rules.facts.TransferRequest;
import io.javalin.Javalin;
import io.javalin.http.Context;
import io.javalin.json.JavalinJackson;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.List;
import java.util.Map;

/** HTTP entry point (Javalin). */
public final class App {

    private static final Logger LOG = LoggerFactory.getLogger(App.class);

    public static final ObjectMapper MAPPER = new ObjectMapper()
            .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false);

    // Request bodies (see docs/API_CONTRACT.md section 2).
    public record ForecastBody(List<QuantityChange> changes, ReviewRequest review) {
    }

    public record AllocationConfigBody(Double baselinePct, String sharing) {
    }

    public record AllocationBody(String mode, AllocationConfigBody config, List<ModelDemand> models) {
    }

    public record TransferBody(TransferRequest transfer) {
    }

    public record ApprovalBody(ApprovalRequest request) {
    }

    private App() {
    }

    public static void main(String[] args) {
        Map<String, String> env = System.getenv();
        int port = Integer.parseInt(env.getOrDefault("PORT", "8080").trim());
        AuthVerifier auth = authFromEnv(env);
        RulesEngine engine = new RulesEngine();
        create(engine, auth).start("0.0.0.0", port);
    }

    /** Builds the verifier from env vars; returns null when AUTH_DISABLED=true. */
    static AuthVerifier authFromEnv(Map<String, String> env) {
        if ("true".equalsIgnoreCase(env.getOrDefault("AUTH_DISABLED", "false").trim())) {
            LOG.warn("AUTH_DISABLED=true: /rules/* endpoints accept requests WITHOUT a token. Local testing only!");
            return null;
        }
        String issuer = env.get("KEYCLOAK_ISSUER");
        if (issuer == null || issuer.isBlank()) {
            throw new IllegalStateException("KEYCLOAK_ISSUER must be set (or AUTH_DISABLED=true for local tests)");
        }
        issuer = issuer.trim();
        String jwks = env.get("KEYCLOAK_JWKS_URL");
        if (jwks == null || jwks.isBlank()) {
            jwks = stripSlash(issuer) + "/protocol/openid-connect/certs";
        }
        String client = env.getOrDefault("ALLOWED_CLIENT", "printer-api-svc").trim();
        LOG.info("Auth enabled: issuer={}, jwks={}, allowed client={}", issuer, jwks, client);
        return new AuthVerifier(issuer, jwks.trim(), client);
    }

    private static String stripSlash(String s) {
        return s.endsWith("/") ? s.substring(0, s.length() - 1) : s;
    }

    /** Creates the (not yet started) Javalin app. {@code auth == null} disables authentication. */
    public static Javalin create(RulesEngine engine, AuthVerifier auth) {
        Javalin app = Javalin.create(cfg -> {
            cfg.showJavalinBanner = false;
            cfg.jsonMapper(new JavalinJackson(MAPPER, false));
        });

        app.before("/rules/*", ctx -> {
            if (auth != null) {
                auth.verify(ctx.header("Authorization"));
            }
        });

        app.get("/health", ctx -> ctx.json(Map.of("status", "UP")));

        app.get("/rules/catalogue", ctx -> ctx.json(Catalogue.RULES));

        app.post("/rules/forecast", ctx -> {
            ForecastBody body = parse(ctx, ForecastBody.class);
            ctx.json(Map.of("violations", engine.evaluateForecast(body.changes(), body.review())));
        });

        app.post("/rules/allocation", ctx -> {
            AllocationBody body = parse(ctx, AllocationBody.class);
            AllocationConfig cfg = toConfig(body);
            List<ModelDemand> models = body.models() == null ? List.of() : body.models();
            for (ModelDemand m : models) {
                if (m == null) {
                    throw new ApiError(400, "models must not contain null");
                }
                checkRegions(m.getDemand(), "demand");
                checkRegions(m.getAllocated(), "allocated");
            }
            RulesEngine.AllocationOutcome out = engine.evaluateAllocation(cfg, models);
            Map<String, Object> result = new java.util.LinkedHashMap<>();
            result.put("allocations", out.allocations());
            result.put("violations", out.violations());
            ctx.json(result);
        });

        app.post("/rules/transfer", ctx -> {
            TransferBody body = parse(ctx, TransferBody.class);
            if (body.transfer() == null) {
                throw new ApiError(400, "Body must contain 'transfer'");
            }
            ctx.json(Map.of("violations", engine.evaluateTransfer(body.transfer())));
        });

        app.post("/rules/approval", ctx -> {
            ApprovalBody body = parse(ctx, ApprovalBody.class);
            if (body.request() == null) {
                throw new ApiError(400, "Body must contain 'request'");
            }
            ctx.json(Map.of("violations", engine.evaluateApproval(body.request())));
        });

        app.exception(ApiError.class, (e, ctx) -> ctx.status(e.getStatus()).json(Map.of("detail", e.getMessage())));
        app.exception(Exception.class, (e, ctx) -> {
            LOG.error("Unhandled error on {} {}", ctx.method(), ctx.path(), e);
            ctx.status(500).json(Map.of("detail", "Internal error"));
        });
        app.error(404, ctx -> ctx.json(Map.of("detail", "Not found")));
        return app;
    }

    private static AllocationConfig toConfig(AllocationBody body) {
        String mode = body.mode();
        if (!"ALLOCATE".equals(mode) && !"VALIDATE".equals(mode)) {
            throw new ApiError(400, "mode must be ALLOCATE or VALIDATE");
        }
        double pct = 25;
        String sharing = AllocationConfig.UNMET_DEMAND;
        if (body.config() != null) {
            if (body.config().baselinePct() != null) {
                pct = body.config().baselinePct();
            }
            if (body.config().sharing() != null) {
                sharing = body.config().sharing();
            }
        }
        if (Double.isNaN(pct) || pct < 0 || pct > 100) {
            throw new ApiError(400, "config.baselinePct must be between 0 and 100");
        }
        if (!AllocationConfig.UNMET_DEMAND.equals(sharing) && !AllocationConfig.PROPORTIONAL.equals(sharing)) {
            throw new ApiError(400, "config.sharing must be UNMET_DEMAND or PROPORTIONAL");
        }
        return new AllocationConfig(mode, pct, sharing);
    }

    private static void checkRegions(Map<String, Double> values, String field) {
        for (String region : values.keySet()) {
            if (!Checks.isValidRegion(region)) {
                throw new ApiError(400, "Unknown region '" + region + "' in " + field
                        + " (expected North, East, West, South)");
            }
        }
    }

    private static <T> T parse(Context ctx, Class<T> type) {
        String raw = ctx.body();
        if (raw == null || raw.isBlank()) {
            throw new ApiError(400, "Request body is required");
        }
        try {
            T value = MAPPER.readValue(raw, type);
            if (value == null) {
                throw new ApiError(400, "Request body must be a JSON object");
            }
            return value;
        } catch (JsonProcessingException e) {
            throw new ApiError(400, "Invalid JSON: " + e.getOriginalMessage());
        }
    }
}
