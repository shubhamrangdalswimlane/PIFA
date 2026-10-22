"""Generate realm-export.json for the `printer-poc` realm.

Run: python keycloak/build_realm.py
Placeholders like ${PIFA_SEED_PASSWORD} are left in the output; Keycloak resolves them
from environment variables when it imports the realm.
"""

import json
from pathlib import Path

REGIONS = ["North", "East", "West", "South"]
ROLES = ["SALES_MANAGER", "REGIONAL_MANAGER", "PLANNER", "HEAD_OF_SALES", "ADMIN"]


def user(username, first, last, role, region=None):
    u = {
        "username": username,
        "enabled": True,
        "emailVerified": True,
        "firstName": first,
        "lastName": last,
        "email": f"{username}@pifa.local",
        "credentials": [{"type": "password", "value": "${PIFA_SEED_PASSWORD}", "temporary": False}],
        "realmRoles": [role],
    }
    if region:
        u["attributes"] = {"region": [region]}
    return u


def attr(name, display, validations=None, edit=("admin", "user")):
    return {
        "name": name,
        "displayName": display,
        "validations": validations or {},
        "permissions": {"view": ["admin", "user"], "edit": list(edit)},
        "multivalued": False,
    }


user_profile = {
    "attributes": [
        # Plain display names: "${...}" message keys would collide with the env placeholders.
        attr("username", "Username", {"length": {"min": 3, "max": 255}, "username-prohibited-characters": {}, "up-username-not-idn-homograph": {}}),
        attr("email", "Email", {"email": {}, "length": {"max": 255}}),
        attr("firstName", "First name", {"length": {"max": 255}, "person-name-prohibited-characters": {}}),
        attr("lastName", "Last name", {"length": {"max": 255}, "person-name-prohibited-characters": {}}),
        attr("region", "Region", {"options": {"options": REGIONS}}, edit=("admin",)),
    ],
    "groups": [{"name": "user-metadata", "displayHeader": "User metadata", "displayDescription": "Attributes, which refer to user metadata"}],
}

users = []
for r in REGIONS:
    users.append(user(f"sm.{r.lower()}", "Sales Manager", r, "SALES_MANAGER", r))
for r in REGIONS:
    users.append(user(f"rm.{r.lower()}", "Regional Manager", r, "REGIONAL_MANAGER", r))
users += [
    user("planner", "Planning", "Lead", "PLANNER"),
    user("head", "Head", "of Sales", "HEAD_OF_SALES"),
    user("admin", "Platform", "Admin", "ADMIN"),
    {
        "username": "service-account-printer-api-svc",
        "enabled": True,
        "serviceAccountClientId": "printer-api-svc",
        "clientRoles": {"realm-management": ["view-users", "query-users"]},
    },
    {"username": "service-account-printer-upstream", "enabled": True, "serviceAccountClientId": "printer-upstream"},
]

realm = {
    "realm": "printer-poc",
    "enabled": True,
    "displayName": "PIFA",
    "sslRequired": "external",
    "accessTokenLifespan": 900,
    "ssoSessionIdleTimeout": 1800,
    "ssoSessionMaxLifespan": 36000,
    "bruteForceProtected": True,
    "failureFactor": 5,
    "loginWithEmailAllowed": False,
    "registrationAllowed": False,
    "resetPasswordAllowed": False,
    "roles": {"realm": [{"name": r, "description": f"PIFA {r}"} for r in ROLES]},
    "clients": [
        {
            "clientId": "printer-web",
            "name": "PIFA web app",
            "enabled": True,
            "publicClient": True,
            "standardFlowEnabled": True,
            "directAccessGrantsEnabled": False,
            "implicitFlowEnabled": False,
            "redirectUris": ["${PIFA_WEB_ORIGIN}/*", "http://localhost:5173/*"],
            "webOrigins": ["${PIFA_WEB_ORIGIN}", "http://localhost:5173"],
            "attributes": {"pkce.code.challenge.method": "S256", "post.logout.redirect.uris": "${PIFA_WEB_ORIGIN}/*##http://localhost:5173/*"},
            "protocolMappers": [
                {
                    "name": "region",
                    "protocol": "openid-connect",
                    "protocolMapper": "oidc-usermodel-attribute-mapper",
                    "config": {
                        "user.attribute": "region",
                        "claim.name": "region",
                        "jsonType.label": "String",
                        "access.token.claim": "true",
                        "id.token.claim": "true",
                        "userinfo.token.claim": "true",
                    },
                },
                {
                    "name": "printer-api audience",
                    "protocol": "openid-connect",
                    "protocolMapper": "oidc-audience-mapper",
                    "config": {"included.client.audience": "printer-api", "access.token.claim": "true", "id.token.claim": "false"},
                },
            ],
        },
        {"clientId": "printer-api", "name": "PIFA API", "enabled": True, "bearerOnly": True, "publicClient": False},
        {
            "clientId": "printer-api-svc",
            "name": "PIFA service-to-service",
            "enabled": True,
            "publicClient": False,
            "secret": "${PIFA_SVC_CLIENT_SECRET}",
            "serviceAccountsEnabled": True,
            "standardFlowEnabled": False,
            "directAccessGrantsEnabled": False,
        },
        {
            "clientId": "printer-upstream",
            "name": "Upstream file drops",
            "enabled": True,
            "publicClient": False,
            "secret": "${PIFA_UPSTREAM_CLIENT_SECRET}",
            "serviceAccountsEnabled": True,
            "standardFlowEnabled": False,
            "directAccessGrantsEnabled": False,
        },
    ],
    "users": users,
    "components": {
        "org.keycloak.userprofile.UserProfileProvider": [
            {
                "providerId": "declarative-user-profile",
                "subComponents": {},
                "config": {"kc.user.profile.config": [json.dumps(user_profile)]},
            }
        ]
    },
}

out = Path(__file__).with_name("realm-export.json")
out.write_text(json.dumps(realm, indent=2) + "\n", encoding="utf-8")
print(f"wrote {out}")
