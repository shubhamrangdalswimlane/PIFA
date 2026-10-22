package com.pifa.rules;

import com.nimbusds.jose.JOSEException;
import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.KeySourceException;
import com.nimbusds.jose.jwk.source.JWKSource;
import com.nimbusds.jose.util.DefaultResourceRetriever;
import com.nimbusds.jose.jwk.source.JWKSourceBuilder;
import com.nimbusds.jose.proc.BadJOSEException;
import com.nimbusds.jose.proc.JWSVerificationKeySelector;
import com.nimbusds.jose.proc.SecurityContext;
import com.nimbusds.jwt.JWTClaimsSet;
import com.nimbusds.jwt.proc.ConfigurableJWTProcessor;
import com.nimbusds.jwt.proc.DefaultJWTClaimsVerifier;
import com.nimbusds.jwt.proc.DefaultJWTProcessor;

import java.net.MalformedURLException;
import java.net.URI;
import java.text.ParseException;
import java.util.Set;

/**
 * Verifies Keycloak client-credentials access tokens: RS256 signature against the realm JWKS (cached),
 * exact issuer, expiry, and {@code azp} equal to the allowed client.
 */
public class AuthVerifier {

    private final ConfigurableJWTProcessor<SecurityContext> processor;
    private final String allowedClient;

    public AuthVerifier(String issuer, String jwksUrl, String allowedClient) {
        this(issuer, remoteJwks(jwksUrl), allowedClient);
    }

    public AuthVerifier(String issuer, JWKSource<SecurityContext> keys, String allowedClient) {
        this.allowedClient = allowedClient;
        this.processor = new DefaultJWTProcessor<>();
        processor.setJWSKeySelector(new JWSVerificationKeySelector<>(JWSAlgorithm.RS256, keys));
        processor.setJWTClaimsSetVerifier(new DefaultJWTClaimsVerifier<>(
                new JWTClaimsSet.Builder().issuer(issuer).build(),
                Set.of("exp")));
    }

    private static JWKSource<SecurityContext> remoteJwks(String jwksUrl) {
        try {
            // Caching (default 5 min TTL) with refresh-ahead and a single retry on network errors.
            // 5 s timeouts: Keycloak on Render may be waking up from sleep.
            return JWKSourceBuilder.<SecurityContext>create(URI.create(jwksUrl).toURL(),
                            new DefaultResourceRetriever(5000, 5000, 512 * 1024))
                    .retrying(true)
                    .build();
        } catch (MalformedURLException | IllegalArgumentException e) {
            throw new IllegalArgumentException("Invalid JWKS URL: " + jwksUrl, e);
        }
    }

    /** Validates the Authorization header value; throws {@link ApiError} 401 on any failure. */
    public JWTClaimsSet verify(String authorizationHeader) {
        if (authorizationHeader == null || authorizationHeader.isBlank()) {
            throw new ApiError(401, "Missing bearer token");
        }
        String[] parts = authorizationHeader.trim().split("\\s+", 2);
        if (parts.length != 2 || !parts[0].equalsIgnoreCase("Bearer") || parts[1].isBlank()) {
            throw new ApiError(401, "Authorization header must be 'Bearer <token>'");
        }
        JWTClaimsSet claims;
        try {
            claims = processor.process(parts[1], null);
        } catch (ParseException e) {
            throw new ApiError(401, "Malformed token");
        } catch (KeySourceException e) {
            throw new ApiError(503, "Identity provider keys unavailable: " + e.getMessage());
        } catch (BadJOSEException e) {
            throw new ApiError(401, "Invalid token: " + e.getMessage());
        } catch (JOSEException e) {
            throw new ApiError(401, "Token could not be verified: " + e.getMessage());
        }
        Object azp = claims.getClaim("azp");
        if (!allowedClient.equals(azp)) {
            throw new ApiError(401, "Token client (azp) not allowed");
        }
        return claims;
    }
}
