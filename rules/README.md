# PIFA rules service

Drools 10 business rules for PIFA, exposed over HTTP (Javalin 6, Java 21). Called by the FastAPI API.
Contract: `docs/API_CONTRACT.md` section 2.

## Endpoints

| Method | Path | Rules |
|---|---|---|
| GET | `/health` (no auth) | `{"status": "UP"}` |
| GET | `/rules/catalogue` | All 8 rules `[{"id", "package", "description"}]` |
| POST | `/rules/forecast` | R-FC-01, R-FC-02, R-FC-03 |
| POST | `/rules/allocation` | `ALLOCATE`: R-ALLOC-01 (+ R-FC-01 on inputs). `VALIDATE`: R-ALLOC-02 + R-FC-01 |
| POST | `/rules/transfer` | R-XFER-01 |
| POST | `/rules/approval` | R-APPR-01, R-XFER-02 |

Every `/rules/*` call needs `Authorization: Bearer <jwt>` (RS256, issuer, expiry, `azp == ALLOWED_CLIENT`).
Errors: `401 {"detail": "..."}` for auth, `503` if Keycloak's JWKS cannot be fetched, `400 {"detail": "..."}` for malformed JSON or bad mode/config/region.
Rule violations are returned with `200` in `violations`; the API decides how to map them (422).

DRL lives in `src/main/resources/rules/{forecast,allocation,transfer,approval}/`. The R-ALLOC-01 arithmetic is in
`AllocationMath` (called from the DRL rule) so it can be unit-tested.

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `8080` | HTTP port |
| `KEYCLOAK_ISSUER` | (required unless auth disabled) | Expected `iss`, e.g. `https://pifa-keycloak.onrender.com/realms/printer-poc` |
| `KEYCLOAK_JWKS_URL` | `${KEYCLOAK_ISSUER}/protocol/openid-connect/certs` | JWKS (cached) |
| `ALLOWED_CLIENT` | `printer-api-svc` | Required `azp` |
| `AUTH_DISABLED` | `false` | `true` skips auth. Local testing only. |
| `JAVA_OPTS` | `-XX:MaxRAMPercentage=75 -XX:+UseSerialGC` | JVM flags |

## Build, test and run (Docker only, no local JDK needed)

```sh
docker build -t pifa-rules .                     # compiles and runs all JUnit tests
docker run --rm -p 8080:8080 -e AUTH_DISABLED=true pifa-rules
curl -s localhost:8080/health
curl -s -X POST localhost:8080/rules/allocation -H 'Content-Type: application/json' \
  -d '{"mode":"ALLOCATE","config":{"baselinePct":25,"sharing":"UNMET_DEMAND"},"models":[{"product":"Model A","inventory":100,"demand":{"North":25,"East":25,"West":25,"South":25}}]}'
```

On Render: Docker web service from `rules/`, set `KEYCLOAK_ISSUER` (and `ALLOWED_CLIENT` if different).
