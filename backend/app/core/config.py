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
    # Separate redirect for Google Sign-In (login/registration) vs. the
    # YouTube channel-connection flow above -- same OAuth client, two
    # different registered redirect URIs, two different scope sets.
    google_signin_redirect_uri: str = "http://localhost:8000/api/v1/auth/google/callback"
    youtube_api_key: str = ""
    # CreatorOS has no way to query Google's own OAuth consent-screen
    # publishing status (that lives entirely in Google Cloud Console, behind
    # a separate API this app doesn't have access to) — this is an explicit,
    # operator-set declaration of what YOU configured there, not something
    # auto-detected. "testing" (the default every new Google Cloud OAuth
    # consent screen starts in) means only accounts added as Test Users can
    # complete the flow; set to "production" only once Google has actually
    # approved verification for the sensitive scopes below.
    youtube_oauth_publishing_status: str = "testing"

    # --- AI ---
    ai_primary_provider: str = "ollama"
    ai_fallback_provider: str = ""
    ollama_base_url: str = "http://localhost:11434"
    # FAST_SMALL tier: the default Ollama model for routine generation/
    # classification tasks (titles, hooks, SEO, captions, summaries, ...).
    # Benchmarked fastest FAST-mode (think=false) average latency among the
    # models installed on this VPS -- see scripts/benchmark_ollama.py and
    # scripts/ollama_benchmark_results.json.
    ollama_model: str = "qwen3-mini:latest"
    # CODING tier: reserved for any future coding-flavored generation task.
    # No current CreatorOS call site is a coding task -- content-engine
    # features (titles/hooks/SEO/scripts/thumbnails) are copywriting, not
    # code generation -- so this is unused today but benchmarked and ready.
    ollama_coding_model: str = "qwen2.5-coder:3b"
    # DEEP tier: only the qwen3 family on this VPS supports think=true at
    # all (gemma2/qwen2.5-coder return a hard 400 "does not support
    # thinking" -- verified in scripts/ollama_benchmark_results.json).
    ollama_deep_model: str = "qwen3:1.7b"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    # OpenRouter: an OpenAI-compatible hosted API that proxies many models
    # (including several free-tier ones) behind one key -- lets this
    # CPU-only VPS use larger/alternative models without a GPU and without
    # depending solely on the paid OpenAI account above. Selectable as
    # AI_PRIMARY_PROVIDER or AI_FALLBACK_PROVIDER, or per-request via
    # POST /api/v1/ai/chat's "provider" field -- never assumed by default.
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # OpenRouter's free-tier model catalog changes over time -- verify the
    # exact slug at https://openrouter.ai/models?max_price=0 before relying
    # on it, and override here (or per-request) rather than hardcoding a
    # model name in application code.
    openrouter_model: str = "openrouter/free"
    # Bounds simultaneous in-flight Ollama requests on this CPU-only, single-
    # model-loaded (OLLAMA_NUM_PARALLEL=1) host so a burst of requests queues
    # instead of all starving each other for CPU. See app/ai/concurrency.py.
    ollama_max_concurrent_requests: int = 2
    ollama_queue_wait_timeout_seconds: float = 30.0
    # How long a cached AI result may be reused before it's treated as
    # stale and regenerated -- see app/ai/cache.py.
    ai_cache_ttl_hours: int = 24

    # --- Video generation (app/video, app/modules/video_generation) ---
    # A global safety net, not a per-user/per-plan billing feature (that
    # would need its own settings table, like publishing's per-channel
    # PublishingRule.max_videos_per_day) -- caps how much a single user can
    # commit to spending on real, billable video generation in a rolling
    # 24h window. create_video_job() sums cost_actual (completed) +
    # cost_estimate (still in flight) for that user's jobs in the last 24h
    # and refuses a new job that would exceed this.
    video_daily_cost_limit_usd: float = 5.0
    video_max_duration_seconds: int = 30
    video_max_concurrent_jobs_per_user: int = 3

    # --- Billing ---
    billing_provider: str = "none"  # "none" (default -- CONFIGURATION_REQUIRED) or "stripe"

    # --- Video processing / transcription ---
    transcription_provider: str = "local"  # "local" (faster-whisper) or "openai"
    whisper_model_size: str = "tiny"  # tiny/base/small/medium/large-v3 -- tiny is CPU-appropriate
    ffmpeg_temp_dir: str = "storage/_tmp_video_processing"

    # --- Object storage ---
    # "local" (default, always works) or "s3" (requires the vars below --
    # falls back to CONFIGURATION_REQUIRED rather than silently using local
    # storage if selected but unconfigured, since that would surprise an
    # operator who explicitly asked for S3-backed persistence).
    storage_backend: str = "local"
    storage_local_path: str = "storage/uploads"
    s3_bucket: str = ""
    s3_region: str = "us-east-1"
    s3_endpoint_url: str = ""  # set for MinIO/S3-compatible deployments
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

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

    @property
    def openrouter_configured(self) -> bool:
        return bool(self.openrouter_api_key)

    @property
    def s3_configured(self) -> bool:
        return bool(self.s3_bucket and self.aws_access_key_id and self.aws_secret_access_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
