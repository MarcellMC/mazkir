"""Vault server FastAPI application."""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.config import settings
from src.services.vault_service import VaultService
from src.services.claude_service import ClaudeService
from src.services.calendar_service import CalendarService
from src.services.memory_service import MemoryService
from src.services.agent_service import AgentService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Service instances (initialized in lifespan)
vault: VaultService | None = None
claude: ClaudeService | None = None
calendar: CalendarService | None = None
memory: MemoryService | None = None
agent: AgentService | None = None
timeline: "TimelineService | None" = None
generation: "GenerationService | None" = None
imagery: "ImageryService | None" = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global vault, claude, calendar, memory, agent, timeline, generation, imagery

    vault = VaultService(settings.vault_path, settings.vault_timezone)
    logger.info(f"Vault service initialized: {settings.vault_path}")

    if settings.anthropic_api_key:
        claude = ClaudeService(api_key=settings.anthropic_api_key)
        logger.info("Claude service initialized")

    # Initialize MemoryService
    memory = MemoryService(
        vault=vault,
        vault_path=settings.vault_path,
        timezone=settings.vault_timezone,
    )
    memory.window_size = settings.conversation_window_size
    memory.initialize()
    logger.info("Memory service initialized")

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

    # Initialize AgentService (requires claude)
    if claude:
        agent = AgentService(
            claude=claude,
            vault=vault,
            memory=memory,
            calendar=calendar,
            data_path=settings.vault_path.parent / "data",
        )
        memory._claude = claude
        logger.info("Agent service initialized")

    from src.services.timeline_service import TimelineService
    if settings.timeline_data_path.exists():
        timeline = TimelineService(
            data_path=settings.timeline_data_path,
            timezone=settings.vault_timezone,
        )
        logger.info(f"Timeline service initialized: {settings.timeline_data_path}")

    from src.services.generation_service import GenerationService
    from src.services.imagery_service import ImageryService
    if settings.replicate_api_token:
        generation = GenerationService(api_token=settings.replicate_api_token)
        logger.info("Generation service initialized")
    imagery = ImageryService()
    logger.info("Imagery service initialized")

    yield


app = FastAPI(title="Mazkir Vault Server", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_vault() -> VaultService:
    assert vault is not None, "Vault service not initialized"
    return vault


def get_claude() -> ClaudeService | None:
    return claude


def get_calendar() -> CalendarService | None:
    return calendar


def get_memory() -> MemoryService | None:
    return memory


def get_agent() -> AgentService | None:
    return agent


def get_timeline():
    return timeline


def get_generation():
    return generation


def get_imagery():
    return imagery


# Register routers
from src.api.routes.tasks import router as tasks_router
from src.api.routes.habits import router as habits_router
from src.api.routes.goals import router as goals_router
from src.api.routes.daily import router as daily_router
from src.api.routes.tokens import router as tokens_router
from src.api.routes.calendar import router as calendar_router
from src.api.routes.message import router as message_router
from src.api.routes.timeline import router as timeline_router
from src.api.routes.merged_events import router as merged_events_router
from src.api.routes.generate import router as generate_router
from src.api.routes.imagery import router as imagery_router

app.include_router(tasks_router)
app.include_router(habits_router)
app.include_router(goals_router)
app.include_router(daily_router)
app.include_router(tokens_router)
app.include_router(calendar_router)
app.include_router(message_router)
app.include_router(timeline_router)
app.include_router(merged_events_router)
app.include_router(generate_router)
app.include_router(imagery_router)


@app.get("/health")
async def health():
    return {"status": "ok", "vault": vault is not None}
