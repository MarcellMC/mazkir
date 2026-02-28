"""Vault server FastAPI application."""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from src.config import settings
from src.services.vault_service import VaultService
from src.services.claude_service import ClaudeService
from src.services.calendar_service import CalendarService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Service instances (initialized in lifespan)
vault: VaultService | None = None
claude: ClaudeService | None = None
calendar: CalendarService | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global vault, claude, calendar

    vault = VaultService(settings.vault_path, settings.vault_timezone)
    logger.info(f"Vault service initialized: {settings.vault_path}")

    if settings.anthropic_api_key:
        claude = ClaudeService(
            api_key=settings.anthropic_api_key,
            vault_path=str(settings.vault_path),
            timezone=settings.vault_timezone,
        )
        logger.info("Claude service initialized")

    if settings.enable_calendar_sync:
        calendar = CalendarService(
            credentials_path=settings.google_credentials_path,
            token_path=settings.google_token_path,
            timezone=settings.vault_timezone,
            default_habit_time=settings.default_habit_time,
            default_event_duration=settings.default_event_duration,
            calendar_id=settings.google_calendar_id,
        )
        if await calendar.initialize():
            await calendar.ensure_mazkir_calendar()
            logger.info("Calendar service initialized")
        else:
            logger.warning("Calendar service failed to initialize")
            calendar = None

    yield


app = FastAPI(title="Mazkir Vault Server", version="0.1.0", lifespan=lifespan)


def get_vault() -> VaultService:
    assert vault is not None, "Vault service not initialized"
    return vault


def get_claude() -> ClaudeService | None:
    return claude


def get_calendar() -> CalendarService | None:
    return calendar


# Register routers
from src.api.routes.tasks import router as tasks_router
from src.api.routes.habits import router as habits_router
from src.api.routes.goals import router as goals_router
from src.api.routes.daily import router as daily_router
from src.api.routes.tokens import router as tokens_router
from src.api.routes.calendar import router as calendar_router
from src.api.routes.message import router as message_router

app.include_router(tasks_router)
app.include_router(habits_router)
app.include_router(goals_router)
app.include_router(daily_router)
app.include_router(tokens_router)
app.include_router(calendar_router)
app.include_router(message_router)


@app.get("/health")
async def health():
    return {"status": "ok", "vault": vault is not None}
