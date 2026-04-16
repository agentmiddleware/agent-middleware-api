"""
Central configuration for the Agent-Native Middleware API.
All settings are loaded from environment variables for zero-GUI deployment.
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """
    Application settings. All values sourced from environment variables.
    Agents authenticate via API keys passed in the X-API-Key header.
    """

    # --- Application ---
    APP_NAME: str = "Agent-Native Middleware API"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False

    # --- Server ---
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    CORS_ORIGINS: str = "*"

    # --- Durable Runtime State ---
    # Backends: auto, postgres, redis, memory
    STATE_BACKEND: str = "auto"
    STATE_NAMESPACE: str = "agent_middleware"
    DATABASE_URL: str = ""
    REDIS_URL: str = ""

    # --- Authentication ---
    API_KEY_HEADER: str = "X-API-Key"
    # Comma-separated list of valid API keys (use a secrets manager in production)
    VALID_API_KEYS: str = ""

    # --- IoT Protocol Bridge ---
    MQTT_BROKER_URL: str = "mqtt://localhost:1883"
    MQTT_DEFAULT_QOS: int = 1
    # Enforce topic-level ACLs to prevent the DJI Romo-style breach pattern
    MQTT_ENFORCE_TOPIC_ACL: bool = True

    # --- Telemetry / Autonomous PM ---
    TELEMETRY_RETENTION_HOURS: int = 168  # 7 days
    AUTO_PR_ENABLED: bool = False
    GIT_REMOTE_URL: str = ""
    GIT_BRANCH_PREFIX: str = "auto-pm/"

    # --- Media Engine ---
    MAX_UPLOAD_SIZE_MB: int = 500
    SUPPORTED_VIDEO_FORMATS: str = "mp4,mov,webm,mkv"
    CAPTION_LANGUAGE: str = "en"

    # --- Rate Limiting ---
    RATE_LIMIT_PER_MINUTE: int = 120

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
