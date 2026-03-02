"""Vault server configuration."""
import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # API
    api_key: str = ""

    # Vault
    vault_path: Path = Path(os.getenv("VAULT_PATH", "/home/marcellmc/pkm"))
    vault_timezone: str = os.getenv("VAULT_TIMEZONE", "Asia/Jerusalem")

    # Claude API
    anthropic_api_key: str | None = None
    claude_model: str = "claude-sonnet-4-20250514"
    claude_max_tokens: int = 4000

    # Google Calendar
    google_credentials_path: Path = Path(
        os.getenv("GOOGLE_CREDENTIALS_PATH", "google_credentials.json")
    )
    google_token_path: Path = Path(
        os.getenv(
            "GOOGLE_TOKEN_PATH",
            os.path.expanduser("~/.config/mazkir/google_token.json"),
        )
    )
    google_calendar_id: str | None = os.getenv("GOOGLE_CALENDAR_ID")
    enable_calendar_sync: bool = (
        os.getenv("ENABLE_CALENDAR_SYNC", "false").lower() == "true"
    )
    default_habit_time: str = os.getenv("DEFAULT_HABIT_TIME", "07:00")
    default_event_duration: int = int(os.getenv("DEFAULT_EVENT_DURATION", "30"))

    # Timeline data
    timeline_data_path: Path = Path(os.getenv("TIMELINE_DATA_PATH", str(Path.home() / "dev" / "mazkir" / "data" / "timeline")))

    # Replicate API (for image generation)
    replicate_api_token: str | None = os.getenv("REPLICATE_API_TOKEN")

    # CORS
    cors_origins: str = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")

    # Memory system
    conversation_window_size: int = 20

    # Application
    log_level: str = "INFO"
    environment: str = "development"


settings = Settings()
