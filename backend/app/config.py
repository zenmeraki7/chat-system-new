from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from typing import List


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@db:5432/chatdb"

    # JWT
    SECRET_KEY: str = "change-me-in-production-use-a-long-random-string"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # OpenAI (single platform-wide key)
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"

    # WhatsApp
    WHATSAPP_ACCESS_TOKEN: str = ""
    WHATSAPP_PHONE_NUMBER_ID: str = ""
    WHATSAPP_BUSINESS_ACCOUNT_ID: str = ""
    WHATSAPP_VERIFY_TOKEN: str = "chat_system_verify_token"
    FB_APP_ID: str = ""
    FB_APP_SECRET: str = ""
    META_APP_ID: str = ""
    META_APP_SECRET: str = ""
    META_EMBEDDED_SIGNUP_CONFIG_ID: str = ""
    META_EMBEDDED_SIGNUP_EXPECTED_ORIGIN: str = "https://app.penpal.example"
    META_GRAPH_API_VERSION: str = "v21.0"
    META_WEBHOOK_VERIFY_TOKEN: str = ""
    WHATSAPP_PHONE_REGISTRATION_PIN: str = ""
    META_REQUIRE_LONG_LIVED_TOKEN: bool = True
    OAUTH_TOKEN_ENCRYPTION_KEY: str = ""
    WHATSAPP_ONBOARDING_PROBE_RECIPIENT_E164: str = ""
    WHATSAPP_ONBOARDING_PROBE_TEXT: str = "Operational probe: onboarding verification message."
    WHATSAPP_ONBOARDING_PROBE_COOLDOWN_SECONDS: int = 300

    # App
    APP_NAME: str = "ChatSystem"
    APP_ENV: str = "development"
    API_V1_STR: str = "/api/v1"
    WIDGET_BASE_URL: str = "http://localhost:8888"
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:8888", "https://7bb0-2409-40f3-10-dd67-f815-bf62-bf2b-b4eb.ngrok-free.app"]

    # Redis / rate limiting
    REDIS_URL: str = ""
    RATE_LIMIT_GLOBAL_MPS: int = 1000
    RATE_LIMIT_BUSINESS_MPS: int = 200
    RATE_LIMIT_WABA_MPS: int = 100
    RATE_LIMIT_PHONE_MPS: int = 50
    RATE_LIMIT_CAMPAIGN_MPS: int = 20
    RATE_LIMIT_RECIPIENT_RETRY_MPS: int = 5
    RATE_LIMIT_MARKETING_PER_CONTACT_PER_DAY: int = 3
    RATE_LIMIT_WEBHOOK_BACKPRESSURE_PENDING_THRESHOLD: int = 500
    RATE_LIMIT_WEBHOOK_BACKPRESSURE_RETRY_AFTER_SECONDS: int = 15
    RATE_LIMIT_FAILURE_WINDOW_MINUTES: int = 15
    RATE_LIMIT_FAILURE_RATE_THROTTLE_THRESHOLD: float = 0.08
    RATE_LIMIT_FAILURE_RATE_PAUSE_THRESHOLD: float = 0.20
    RATE_LIMIT_MIN_DYNAMIC_MULTIPLIER: float = 0.20
    RATE_LIMIT_YELLOW_QUALITY_MULTIPLIER: float = 0.40
    RATE_LIMIT_GREEN_QUALITY_MULTIPLIER: float = 1.0
    RATE_LIMIT_UNKNOWN_QUALITY_MULTIPLIER: float = 0.70
    RATE_LIMIT_RED_QUALITY_RETRY_AFTER_SECONDS: int = 300
    QUALITY_GUARD_FAILED_RATE_15M_THRESHOLD: float = 0.10
    QUALITY_GUARD_UNSUBSCRIBE_RATE_THRESHOLD: float = 0.03
    QUALITY_GUARD_THROTTLE_DELAY_SECONDS: int = 45
    WORKER_REGION: str = "global"
    DEGRADATION_MODE: str = "normal"

@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
