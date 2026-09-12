"""Central application configuration, loaded from environment variables.

All modules read settings from here rather than calling os.environ directly,
so behavior stays testable and there is exactly one source of truth.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Core ---
    environment: str = "development"
    app_name: str = "CreatorOS"
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000"

    # --- Database ---
    database_url: str = "postgresql+asyncpg://creatoros:creatoros@localhost:5432/creatoros"
    database_url_sync: str = "postgresql+psycopg://creatoros:creatoros@localhost:5432/creatoros"

    # --- Redis / Celery ---
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # --- Auth ---
    jwt_secret: str = "change-me-to-a-random-64-byte-secret"
    # Fernet key (base64, 32 bytes) used to encrypt OAuth tokens at rest.
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    encryption_key: str = "change-me-generate-a-real-fernet-key-before-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30
    cookie_secure: bool = False
    cookie_domain: str = "localhost"

    # --- YouTube ---
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    youtube_redirect_uri: str = "http://localhost:8000/api/v1/channels/oauth/callback"
    youtube_api_key: str = ""

    # --- AI ---
    ai_primary_provider: str = "ollama"
    ai_fallback_provider: str = ""
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3-mini"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"

    # --- Notifications ---
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "notifications@creatoros.local"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def youtube_configured(self) -> bool:
        return bool(self.youtube_client_id and self.youtube_client_secret)

    @property
    def openai_configured(self) -> bool:
        return bool(self.openai_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
