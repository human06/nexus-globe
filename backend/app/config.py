"""Pydantic Settings — loads configuration from .env / environment variables."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://nexus:nexus@localhost:5432/nexus"
    redis_url: str = "redis://localhost:6379"

    # API keys
    anthropic_api_key: str = ""
    google_maps_api_key: str = ""

    # OpenSky
    opensky_username: str = ""
    opensky_password: str = ""

    # AISHub
    aishub_api_key: str = ""

    # ACLED
    acled_api_key: str = ""
    acled_email: str = ""


settings = Settings()
