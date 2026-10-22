# Keycloak for PIFA (Render web service). Realm `printer-poc` is imported on first start;
# ${PIFA_*} placeholders in realm-export.json are resolved from environment variables.
FROM quay.io/keycloak/keycloak:26.4 AS builder
ENV KC_DB=postgres \
    KC_HEALTH_ENABLED=true
RUN /opt/keycloak/bin/kc.sh build

FROM quay.io/keycloak/keycloak:26.4
COPY --from=builder /opt/keycloak/ /opt/keycloak/
COPY realm-export.json /opt/keycloak/data/import/printer-poc.json
ENV KC_DB=postgres \
    KC_HTTP_ENABLED=true \
    KC_HTTP_PORT=8080 \
    KC_PROXY_HEADERS=xforwarded \
    KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true
EXPOSE 8080
ENTRYPOINT ["/opt/keycloak/bin/kc.sh"]
CMD ["start", "--optimized", "--import-realm"]
