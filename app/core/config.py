from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    APP_ENV: Literal["local", "dev", "prod"] = "local"
    APP_NAME: str = "fsc-order-microservice"
    APP_VERSION: str = "0.1.0"
    DATABASE_URL: str
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"

    USER_MS_BASE_URL: str = ""
    USER_MS_INTERNAL_VALIDATE_PATH: str = "/api/u1/users/internal/validate"
    USER_MS_INTERNAL_LIST_RECOVERY_IDS_PATH: str = "/api/u1/users/internal/list-recovery-user-ids"
    USER_MS_INTERNAL_PROFILE_PATH: str = "/api/u1/users/internal/profile"
    USER_MS_INTERNAL_API_KEY: str = ""

    VEHICLE_MS_BASE_URL: str = ""
    VEHICLE_MS_INTERNAL_DETAILS_PATH: str = "/api/v1/vehicles/internal/details"
    VEHICLE_MS_INTERNAL_API_KEY: str = ""

    NOTIFICATION_MS_BASE_URL: str = ""
    NOTIFICATION_MS_SEND_PATH: str = "/api/v1/notifications/send"
    NOTIFICATION_INTERNAL_API_KEY: str = ""

    REDIS_URL: str = ""
    HTTP_CLIENT_TIMEOUT_SEC: float = 15.0

    LOCAL_UPLOAD_DIR: str = "uploads"
    PUBLIC_APP_URL: str = "http://localhost:8003"
    UPLOAD_MAX_MB: int = Field(default=15, description="Max job photo upload (MB)")

    # AWS S3 uploads (optional; when configured, job photos go to S3 instead of local disk)
    AWS_S3_BUCKET: str = ""
    AWS_REGION: str = ""
    AWS_PUBLIC_BASE_URL: str = ""
    AWS_UPLOAD_PREFIX: str = ""
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""

    # Capacity / scheduling
    MAX_SERVICE_BOOKINGS_PER_SLOT: int = Field(default=10, description="Max service bookings per exact scheduled_at slot")
    DRIVER_BUSY_WINDOW_MIN: int = Field(default=60, description="Minutes around scheduled_at that counts as a conflict for a driver")

    # Stripe (optional; enable card/wallet payments when set)
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[arg-type]


settings = get_settings()
