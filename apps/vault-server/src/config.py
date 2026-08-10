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
    claude_model: str = "claude-sonnet-4-6"
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
    google_calendar_include: str = os.getenv("GOOGLE_CALENDAR_INCLUDE", "")
    default_habit_time: str = os.getenv("DEFAULT_HABIT_TIME", "07:00")
    default_event_duration: int = int(os.getenv("DEFAULT_EVENT_DURATION", "30"))

    # Media / data paths
    media_path: Path = Path(os.getenv(
        "MEDIA_PATH",
        str(Path.home() / "dev" / "mazkir" / "memory" / "00-system" / "media"),
    ))

    # Timeline data
    timeline_data_path: Path = Path(os.getenv("TIMELINE_DATA_PATH", str(Path.home() / "dev" / "mazkir" / "data" / "timeline")))

    # Persisted events
    events_data_path: Path = Path(os.getenv("EVENTS_DATA_PATH", str(Path.home() / "dev" / "mazkir" / "data" / "events")))

    # Structured logs
    logs_dir: Path = Path(os.getenv("LOGS_DIR", str(Path.home() / "dev" / "mazkir" / "data" / "logs")))

    # Skills directory
    skills_dir: Path = Path(os.getenv(
        "MAZKIR_SKILLS_DIR",
        str(Path.home() / "dev" / "mazkir" / "memory" / "00-system" / "skills"),
    ))

    # Tracing (OTLP/HTTP)
    otel_exporter_otlp_endpoint: str = os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "http://localhost:6006/v1/traces",
    )
    otel_service_name: str = os.getenv("OTEL_SERVICE_NAME", "vault-server")

    # Replicate API (for image generation)
    replicate_api_token: str | None = os.getenv("REPLICATE_API_TOKEN")

    # CORS
    cors_origins: str = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")

    # Memory system
    conversation_window_size: int = 20

    # Coding-handoff
    telegram_bot_token: str | None = os.getenv("TELEGRAM_BOT_TOKEN")
    coding_tasks_data_path: Path = Path(os.getenv(
        "CODING_TASKS_DATA_PATH",
        str(Path.home() / "dev" / "mazkir" / "data" / "coding-tasks"),
    ))
    # Sessions live outside the repo. Deliberately not .claude/worktrees/,
    # which belongs to Claude Code's own linked worktrees -- mixing clones
    # into it makes them invisible to every cleanup path.
    coding_agent_worktrees_path: Path = Path(os.getenv(
        "AGENT_SESSIONS_ROOT",
        str(Path.home() / "dev" / "agent-sessions"),
    ))
    # session.sh owns provisioning, credentials, and launching for every
    # lane. vault-server shells out to it rather than building a second
    # docker invocation, which is what let the two paths drift apart.
    coding_agent_session_script: Path = Path(os.getenv(
        "CODING_AGENT_SESSION_SCRIPT",
        str(Path.home() / "dev" / "mazkir" / "infra" / "coding-agent" / "session.sh"),
    ))
    coding_agent_docker_image: str = os.getenv("CODING_AGENT_DOCKER_IMAGE", "mazkir-coding-agent:latest")
    coding_agent_poll_interval_seconds: float = float(os.getenv("CODING_AGENT_POLL_INTERVAL_SECONDS", "30"))
    mazkir_repo_path: Path = Path(os.getenv("MAZKIR_REPO_PATH", str(Path.home() / "dev" / "mazkir")))
    coding_agent_github_token_path: Path | None = (
        Path(os.environ["CODING_AGENT_GITHUB_TOKEN_PATH"])
        if os.getenv("CODING_AGENT_GITHUB_TOKEN_PATH")
        else None
    )
    mazkir_vault_repo_path: Path = Path(os.getenv(
        "MAZKIR_VAULT_REPO_PATH",
        str(Path.home() / "dev" / "mazkir" / "memory"),
    ))
    # Mirrors CLAUDE_JSON_PATH in infra/coding-agent/devcontainer.sh -- the
    # automated and interactive paths must share the same onboarding/trust
    # state file. See SETUP.md step 2.
    coding_agent_claude_json_path: Path = Path(os.getenv(
        "CODING_AGENT_CLAUDE_JSON_PATH",
        str(Path.home() / ".config" / "mazkir" / "coding-agent-claude-home.json"),
    ))

    # Application
    log_level: str = "INFO"
    environment: str = "development"


settings = Settings()
