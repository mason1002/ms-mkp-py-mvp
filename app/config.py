from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, case_sensitive=False)

    marketplace_mode: str = "mock"  # mock | live

    marketplace_api_base: str = "https://marketplaceapi.microsoft.com"
    marketplace_api_version: str = "2018-08-31"

    database_path: str = "./data/app.db"

    # Admin UI
    # If ADMIN_ENABLED is not set:
    # - enabled in mock mode
    # - disabled in live mode
    admin_enabled: bool | None = Field(default=None, validation_alias="ADMIN_ENABLED")

    def is_admin_enabled(self) -> bool:
        if self.admin_enabled is not None:
            return bool(self.admin_enabled)
        return self.marketplace_mode.lower() != "live"

    # Live-mode auth
    # Env vars: ENTRA_TENANT_ID / ENTRA_CLIENT_ID / ENTRA_CLIENT_SECRET
    entra_tenant_id: str | None = Field(default=None, validation_alias="ENTRA_TENANT_ID")
    entra_client_id: str | None = Field(default=None, validation_alias="ENTRA_CLIENT_ID")
    entra_client_secret: str | None = Field(default=None, validation_alias="ENTRA_CLIENT_SECRET")


def get_settings() -> Settings:
    return Settings()
