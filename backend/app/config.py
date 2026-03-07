"""Pydantic Settings — loads configuration from .env / environment variables."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://nexus:nexus@localhost:5432/nexus"
    redis_url: str = "redis://localhost:6379"

    # API keys (legacy)
    google_maps_api_key: str = ""

    # AI — OpenRouter (Story 2.8)
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    ai_model: str = "google/gemini-2.5-flash-preview"
    ai_model_fallback: str = "deepseek/deepseek-chat-v3-0324"
    ai_max_tokens: int = 500
    ai_temperature: float = 0.3
    ai_max_requests_per_minute: int = 30

    # News sources (Story 2.2)
    event_registry_api_key: str = ""

    # OpenSky
    opensky_username: str = ""
    opensky_password: str = ""

    # AISHub (legacy — use AISstream instead)
    aishub_api_key: str = ""

    # AISstream.io — free WebSocket AIS feed (https://aisstream.io/apikeys)
    aisstream_api_key: str = ""

    # ACLED
    acled_api_key: str = ""
    acled_email: str = ""

    # Traffic — TomTom Traffic Flow API (free tier)
    # Register at https://developer.tomtom.com/
    tomtom_api_key: str = ""


settings = Settings()
