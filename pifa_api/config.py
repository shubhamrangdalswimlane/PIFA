from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://pifa:pifa@localhost:5432/pifa"
    db_schema: str = "pifa"
    auto_migrate: bool = True

    # Expected `iss` of user and service tokens (public Keycloak URL).
    keycloak_issuer: str = "http://localhost:8080/realms/printer-poc"
    # Base URL the API uses to reach Keycloak (JWKS, token, admin). Defaults to the issuer's host.
    keycloak_internal_url: str | None = None
    keycloak_audience: str = "printer-api"

    svc_client_id: str = "printer-api-svc"
    svc_client_secret: str = ""

    files_url: str = "http://localhost:8082"
    http_timeout: float = 10.0

    allowed_origins: str = "http://localhost:5173"

    @property
    def realm(self) -> str:
        return self.keycloak_issuer.rstrip("/").rsplit("/", 1)[-1]

    @property
    def keycloak_base(self) -> str:
        """Keycloak root URL (without /realms/...) used for server-to-server calls."""
        if self.keycloak_internal_url:
            return self.keycloak_internal_url.rstrip("/")
        return self.keycloak_issuer.split("/realms/")[0]

    @property
    def realm_base(self) -> str:
        return f"{self.keycloak_base}/realms/{self.realm}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
