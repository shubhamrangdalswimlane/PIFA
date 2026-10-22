package com.pifa.rules;

import com.fasterxml.jackson.databind.JsonNode;
import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.JWSHeader;
import com.nimbusds.jose.crypto.RSASSASigner;
import com.nimbusds.jose.jwk.JWKSet;
import com.nimbusds.jose.jwk.RSAKey;
import com.nimbusds.jose.jwk.gen.RSAKeyGenerator;
import com.nimbusds.jose.jwk.source.ImmutableJWKSet;
import com.nimbusds.jwt.JWTClaimsSet;
import com.nimbusds.jwt.SignedJWT;
import io.javalin.Javalin;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.Date;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** End-to-end HTTP tests: one app with auth disabled, one with auth against a local RSA key. */
class HttpApiTest {

    private static final String ISSUER = "https://kc.example.test/realms/printer-poc";
    private static final HttpClient CLIENT = HttpClient.newHttpClient();

    private static Javalin open;
    private static Javalin secured;
    private static RSAKey key;

    @BeforeAll
    static void start() throws Exception {
        RulesEngine engine = new RulesEngine();
        open = App.create(engine, null).start("127.0.0.1", 0);
        key = new RSAKeyGenerator(2048).keyID("k1").generate();
        AuthVerifier auth = new AuthVerifier(ISSUER, new ImmutableJWKSet<>(new JWKSet(key.toPublicJWK())), "printer-api-svc");
        secured = App.create(engine, auth).start("127.0.0.1", 0);
    }

    @AfterAll
    static void stop() {
        open.stop();
        secured.stop();
    }

    private static HttpResponse<String> call(Javalin app, String method, String path, String body, String token) throws Exception {
        HttpRequest.Builder b = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + app.port() + path))
                .header("Content-Type", "application/json");
        if (token != null) {
            b.header("Authorization", "Bearer " + token);
        }
        b.method(method, body == null ? HttpRequest.BodyPublishers.noBody() : HttpRequest.BodyPublishers.ofString(body));
        return CLIENT.send(b.build(), HttpResponse.BodyHandlers.ofString());
    }

    private static JsonNode json(HttpResponse<String> r) throws Exception {
        return App.MAPPER.readTree(r.body());
    }

    private static String token(String issuer, String azp, long expiresInSeconds) throws Exception {
        JWTClaimsSet claims = new JWTClaimsSet.Builder()
                .issuer(issuer)
                .subject("service-account-printer-api-svc")
                .claim("azp", azp)
                .issueTime(new Date())
                .expirationTime(new Date(System.currentTimeMillis() + expiresInSeconds * 1000))
                .build();
        SignedJWT jwt = new SignedJWT(new JWSHeader.Builder(JWSAlgorithm.RS256).keyID("k1").build(), claims);
        jwt.sign(new RSASSASigner(key));
        return jwt.serialize();
    }

    @Test
    void healthIsOpen() throws Exception {
        HttpResponse<String> r = call(secured, "GET", "/health", null, null);
        assertEquals(200, r.statusCode());
        assertEquals("UP", json(r).get("status").asText());
    }

    @Test
    void catalogueListsEightRules() throws Exception {
        HttpResponse<String> r = call(open, "GET", "/rules/catalogue", null, null);
        assertEquals(200, r.statusCode());
        JsonNode arr = json(r);
        assertEquals(8, arr.size());
        assertEquals("R-FC-01", arr.get(0).get("id").asText());
        assertEquals("forecast", arr.get(0).get("package").asText());
        assertTrue(arr.get(0).has("description"));
    }

    @Test
    void allocationWorkedExampleOverHttp() throws Exception {
        String body = """
                {"mode":"ALLOCATE","config":{"baselinePct":25,"sharing":"UNMET_DEMAND"},
                 "models":[{"product":"Model A","inventory":100,"demand":{"North":25,"East":25,"West":25,"South":25}}]}""";
        HttpResponse<String> r = call(open, "POST", "/rules/allocation", body, null);
        assertEquals(200, r.statusCode(), r.body());
        JsonNode j = json(r);
        assertEquals(4, j.get("allocations").size());
        for (JsonNode a : j.get("allocations")) {
            assertEquals(25, a.get("qty").asLong());
            assertTrue(a.get("qty").isIntegralNumber());
        }
        assertEquals(0, j.get("violations").size());
    }

    @Test
    void forecastViolationShape() throws Exception {
        String body = """
                {"changes":[{"entity":"forecast","product":"Model A","region":"North","qty":2.5,"comment":"","isRevision":true}],
                 "review":null}""";
        HttpResponse<String> r = call(open, "POST", "/rules/forecast", body, null);
        assertEquals(200, r.statusCode());
        JsonNode vs = json(r).get("violations");
        assertEquals(2, vs.size());
        assertEquals("R-FC-01", vs.get(0).get("ruleId").asText());
        assertEquals("Model A", vs.get(0).get("product").asText());
        assertEquals("North", vs.get(0).get("region").asText());
        assertEquals("R-FC-02", vs.get(1).get("ruleId").asText());
    }

    @Test
    void transferAndApprovalEndpoints() throws Exception {
        HttpResponse<String> t = call(open, "POST", "/rules/transfer",
                "{\"transfer\":{\"product\":\"Model A\",\"fromRegion\":\"East\",\"toRegion\":\"North\",\"qty\":5,\"sourceQty\":25,\"comment\":\"ok\"}}", null);
        assertEquals(200, t.statusCode());
        assertEquals(0, json(t).get("violations").size());
        HttpResponse<String> a = call(open, "POST", "/rules/approval",
                "{\"request\":{\"actorRole\":\"PLANNER\",\"decision\":\"APPROVE\",\"comment\":\"\",\"stage\":5}}", null);
        assertEquals(200, a.statusCode());
        assertEquals("R-APPR-01", json(a).get("violations").get(0).get("ruleId").asText());
    }

    @Test
    void badJsonIs400() throws Exception {
        HttpResponse<String> r = call(open, "POST", "/rules/forecast", "{not json", null);
        assertEquals(400, r.statusCode());
        assertTrue(json(r).has("detail"));
        assertEquals(400, call(open, "POST", "/rules/allocation", "{\"mode\":\"NOPE\"}", null).statusCode());
        assertEquals(400, call(open, "POST", "/rules/transfer", "{}", null).statusCode());
    }

    @Test
    void securedRejectsMissingAndBadTokens() throws Exception {
        HttpResponse<String> none = call(secured, "GET", "/rules/catalogue", null, null);
        assertEquals(401, none.statusCode());
        assertTrue(json(none).get("detail").isTextual());
        assertEquals(401, call(secured, "GET", "/rules/catalogue", null, "garbage").statusCode());
        assertEquals(401, call(secured, "GET", "/rules/catalogue", null, token(ISSUER, "printer-web", 300)).statusCode());
        assertEquals(401, call(secured, "GET", "/rules/catalogue", null, token("https://evil.test/realms/x", "printer-api-svc", 300)).statusCode());
        assertEquals(401, call(secured, "GET", "/rules/catalogue", null, token(ISSUER, "printer-api-svc", -600)).statusCode());
        // Auth runs before body parsing: no token on a POST is 401, not 400.
        assertEquals(401, call(secured, "POST", "/rules/forecast", "{bad", null).statusCode());
    }

    @Test
    void securedAcceptsValidServiceToken() throws Exception {
        HttpResponse<String> r = call(secured, "GET", "/rules/catalogue", null, token(ISSUER, "printer-api-svc", 300));
        assertEquals(200, r.statusCode(), r.body());
        assertEquals(8, json(r).size());
    }
}
