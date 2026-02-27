# Monorepo Migration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reorganize Mazkir into a Turborepo monorepo with a FastAPI vault-server and thin Telegram client.

**Architecture:** Turborepo at `~/dev/mazkir/` with two Python apps (`vault-server` and `telegram-py-client`), plus an Obsidian vault (`memory/`) as a gitignored nested repo. The vault-server owns all business logic (vault CRUD, Claude AI, Google Calendar). The Telegram client is a thin UI layer.

**Tech Stack:** Turborepo, FastAPI, uvicorn, httpx, Telethon, python-frontmatter, anthropic SDK, Google Calendar API

**Design doc:** `docs/plans/2026-02-28-monorepo-migration-design.md`

---

## Phase 1: GitHub Repo Renames

### Task 1: Rename GitHub repos and update local remotes

**Context:** Currently `MarcellMC/mazkir` is the vault (~/pkm/) and `MarcellMC/mazkir-bot` is the bot (~/dev/tg-mazkir/). We rename vault repo to `mazkir-memory` and bot repo to `mazkir`.

**Step 1: Rename repos on GitHub**

Do this manually on github.com:
1. Go to `github.com/MarcellMC/mazkir` → Settings → Rename to `mazkir-memory`
2. Go to `github.com/MarcellMC/mazkir-bot` → Settings → Rename to `mazkir`

**Step 2: Update vault remote**

```bash
cd ~/pkm
git remote set-url origin git@github.com:MarcellMC/mazkir-memory.git
git remote -v  # Verify: should show mazkir-memory
```

**Step 3: Update bot remote**

```bash
cd ~/dev/tg-mazkir
git remote set-url origin git@github.com:MarcellMC/mazkir.git
git remote -v  # Verify: should show mazkir
```

**Step 4: Verify both repos push/pull correctly**

```bash
cd ~/pkm && git fetch origin
cd ~/dev/tg-mazkir && git fetch origin
```

**Step 5: Commit** — No commit needed (remote URL changes are local config).

---

## Phase 2: Monorepo Skeleton

### Task 2: Initialize Turborepo at the bot repo root

**Files:**
- Create: `~/dev/tg-mazkir/package.json`
- Create: `~/dev/tg-mazkir/turbo.json`

**Step 1: Create root package.json**

```json
{
  "name": "mazkir",
  "private": true,
  "workspaces": ["apps/*"],
  "scripts": {
    "dev": "turbo dev",
    "test": "turbo test",
    "lint": "turbo lint"
  },
  "devDependencies": {
    "turbo": "^2"
  }
}
```

**Step 2: Create turbo.json**

```json
{
  "$schema": "https://turbo.build/schema.json",
  "tasks": {
    "dev": {
      "cache": false,
      "persistent": true
    },
    "test": {},
    "lint": {}
  }
}
```

**Step 3: Install turborepo**

Run: `cd ~/dev/tg-mazkir && npm install`
Expected: `node_modules/` created, `package-lock.json` generated

**Step 4: Add node_modules to .gitignore**

Append to `.gitignore`:
```
node_modules/
```

**Step 5: Commit**

```bash
git add package.json turbo.json package-lock.json .gitignore
git commit -m "feat: initialize Turborepo monorepo skeleton"
```

---

### Task 3: Move bot code into apps/telegram-py-client/

**Context:** Move ALL existing bot source code from the repo root into `apps/telegram-py-client/`. This is a file move, not a rewrite.

**Step 1: Create apps directory and move files**

```bash
cd ~/dev/tg-mazkir
mkdir -p apps/telegram-py-client

# Move bot source and config
mv src/ apps/telegram-py-client/
mv requirements.txt apps/telegram-py-client/
mv .env apps/telegram-py-client/
mv .env.example apps/telegram-py-client/
mv docker-compose.yml apps/telegram-py-client/

# Move bot docs
mv README.md apps/telegram-py-client/
mv tg-mazkir-AGENTS.md apps/telegram-py-client/
mv tg-mazkir-IMPLEMENTATION.md apps/telegram-py-client/
mv tg-mazkir-WEBAPP.md apps/telegram-py-client/
mv SEMANTIC_SEARCH.md apps/telegram-py-client/

# Move database migrations
mv alembic/ apps/telegram-py-client/
mv docker/ apps/telegram-py-client/

# Move venv (or recreate later)
mv venv/ apps/telegram-py-client/

# Move session file if exists
mv mazkir_bot_session.session apps/telegram-py-client/ 2>/dev/null || true

# Move google credentials if in root
mv google_credentials.json apps/telegram-py-client/ 2>/dev/null || true
```

**Step 2: Fix Python imports**

The bot uses `from src.config import settings` etc. Since we moved `src/` into `apps/telegram-py-client/src/`, the imports stay the same AS LONG AS we run from `apps/telegram-py-client/`. No import changes needed.

**Step 3: Create app-level package.json for Turborepo**

Create `apps/telegram-py-client/package.json`:
```json
{
  "name": "telegram-py-client",
  "private": true,
  "scripts": {
    "dev": "python -m src.main",
    "test": "pytest tests/",
    "lint": "ruff check src/"
  }
}
```

**Step 4: Verify bot still runs**

```bash
cd ~/dev/tg-mazkir/apps/telegram-py-client
source venv/bin/activate
python -m src.main
```
Expected: Bot starts and shows "Mazkir Bot is running!"
Stop with Ctrl+C after verifying.

**Step 5: Commit**

```bash
cd ~/dev/tg-mazkir
git add -A
git commit -m "refactor: move bot code into apps/telegram-py-client"
```

---

### Task 4: Move existing root docs into monorepo root

**Context:** The coordination repo `~/dev/mazkir/` has `CLAUDE.md`, `personal-ai-assistant-roadmap.md`, and `docs/plans/`. These need to merge into the bot repo (which is becoming the monorepo). Since `~/dev/mazkir/` is NOT a git repo, we just copy files.

**Step 1: Copy docs from coordination repo**

```bash
cd ~/dev/tg-mazkir

# Copy CLAUDE.md (will be rewritten later, but preserve for now)
cp ~/dev/mazkir/CLAUDE.md ./CLAUDE.md

# Copy roadmap
cp ~/dev/mazkir/personal-ai-assistant-roadmap.md ./

# Copy design docs
mkdir -p docs/plans
cp ~/dev/mazkir/docs/plans/*.md docs/plans/

# Copy .claude settings if present
cp -r ~/dev/mazkir/.claude . 2>/dev/null || true
```

**Step 2: Commit**

```bash
git add CLAUDE.md personal-ai-assistant-roadmap.md docs/ .claude/
git commit -m "docs: merge coordination repo docs into monorepo root"
```

---

## Phase 3: Move Vault Into Place

### Task 5: Move vault to memory/ and create symlink

**Context:** `~/pkm/` is an Obsidian vault with its own git repo (remote: `mazkir-memory`). We move it into the monorepo as `memory/`, gitignore it, and symlink `~/pkm/` back.

**Step 1: Add memory/ to monorepo .gitignore**

Append to `~/dev/tg-mazkir/.gitignore`:
```
memory/
```

**Step 2: Move vault into monorepo**

```bash
# Move the entire vault (including .git)
mv ~/pkm ~/dev/tg-mazkir/memory
```

**Step 3: Create symlink for Obsidian compatibility**

```bash
ln -s ~/dev/tg-mazkir/memory ~/pkm
```

**Step 4: Verify vault git still works**

```bash
cd ~/dev/tg-mazkir/memory
git status
git remote -v  # Should show mazkir-memory
```

**Step 5: Verify Obsidian can still open the vault**

Open Obsidian and verify it opens `~/pkm/` (the symlink) normally.

**Step 6: Update VAULT_PATH in telegram client .env**

Edit `apps/telegram-py-client/.env`:
Change `VAULT_PATH=/home/marcellmc/pkm` → keep as-is (symlink makes it work), OR update to `VAULT_PATH=/home/marcellmc/dev/tg-mazkir/memory`. Either works since the symlink resolves correctly.

**Step 7: Commit monorepo .gitignore change**

```bash
cd ~/dev/tg-mazkir
git add .gitignore
git commit -m "chore: gitignore memory/ directory (vault is nested repo)"
```

---

### Task 6: Rename local directory from tg-mazkir to mazkir

**Context:** The repo is now the monorepo. Rename the local directory to match.

**Step 1: Rename directory**

```bash
# Remove the old mazkir coordination directory (no git repo, just docs we already copied)
rm -rf ~/dev/mazkir

# Rename tg-mazkir to mazkir
mv ~/dev/tg-mazkir ~/dev/mazkir
```

**Step 2: Fix the pkm symlink** (it pointed to tg-mazkir)

```bash
rm ~/pkm
ln -s ~/dev/mazkir/memory ~/pkm
ls ~/pkm/AGENTS.md  # Verify symlink works
```

**Step 3: Verify everything still works**

```bash
cd ~/dev/mazkir
git status                    # Monorepo git works
ls apps/telegram-py-client/   # Bot code is here
ls memory/AGENTS.md           # Vault is here
cd memory && git status       # Vault git works
```

**Step 4: Commit** — No commit needed (directory rename is outside git).

---

## Phase 4: Build Vault Server

### Task 7: Scaffold vault-server FastAPI app

**Files:**
- Create: `apps/vault-server/package.json`
- Create: `apps/vault-server/pyproject.toml`
- Create: `apps/vault-server/src/__init__.py`
- Create: `apps/vault-server/src/main.py`
- Create: `apps/vault-server/src/config.py`
- Create: `apps/vault-server/.env.example`

**Step 1: Create directory structure**

```bash
cd ~/dev/mazkir
mkdir -p apps/vault-server/src/api/routes
mkdir -p apps/vault-server/src/services
mkdir -p apps/vault-server/tests
touch apps/vault-server/src/__init__.py
touch apps/vault-server/src/api/__init__.py
touch apps/vault-server/src/api/routes/__init__.py
touch apps/vault-server/src/services/__init__.py
touch apps/vault-server/tests/__init__.py
```

**Step 2: Create package.json**

Create `apps/vault-server/package.json`:
```json
{
  "name": "vault-server",
  "private": true,
  "scripts": {
    "dev": "python -m uvicorn src.main:app --reload --port 8000",
    "test": "pytest tests/ -v",
    "lint": "ruff check src/"
  }
}
```

**Step 3: Create pyproject.toml**

Create `apps/vault-server/pyproject.toml`:
```toml
[project]
name = "vault-server"
version = "0.1.0"
description = "Mazkir vault REST API server"
requires-python = ">=3.12"

dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "python-frontmatter>=1.0.0",
    "python-dateutil>=2.8.2",
    "pytz>=2024.1",
    "anthropic>=0.18.0",
    "google-api-python-client>=2.100.0",
    "google-auth-httplib2>=0.1.0",
    "google-auth-oauthlib>=1.0.0",
    "pydantic>=2.5.0",
    "pydantic-settings>=2.1.0",
    "python-dotenv>=1.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "httpx>=0.27.0",
    "ruff>=0.5.0",
]
```

**Step 4: Create config.py**

Create `apps/vault-server/src/config.py`:
```python
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
    api_key: str = ""  # Shared secret for auth

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

    # Application
    log_level: str = "INFO"
    environment: str = "development"


settings = Settings()
```

**Step 5: Create main.py with health check**

Create `apps/vault-server/src/main.py`:
```python
"""Vault server FastAPI application."""
import logging
from fastapi import FastAPI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

app = FastAPI(title="Mazkir Vault Server", version="0.1.0")


@app.get("/health")
async def health():
    return {"status": "ok"}
```

**Step 6: Create .env.example**

Create `apps/vault-server/.env.example`:
```
# API Authentication
API_KEY=your_shared_secret_here

# Vault Configuration
VAULT_PATH=/home/marcellmc/pkm
VAULT_TIMEZONE=Asia/Jerusalem

# Claude API
ANTHROPIC_API_KEY=your_anthropic_api_key_here
CLAUDE_MODEL=claude-sonnet-4-20250514
CLAUDE_MAX_TOKENS=4000

# Google Calendar Integration
ENABLE_CALENDAR_SYNC=false
GOOGLE_CREDENTIALS_PATH=google_credentials.json
GOOGLE_TOKEN_PATH=~/.config/mazkir/google_token.json
DEFAULT_HABIT_TIME=07:00
DEFAULT_EVENT_DURATION=30
```

**Step 7: Create venv and install deps**

```bash
cd ~/dev/mazkir/apps/vault-server
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

**Step 8: Verify server starts**

```bash
cd ~/dev/mazkir/apps/vault-server
source venv/bin/activate
python -m uvicorn src.main:app --port 8000
```
Expected: Server starts on port 8000.
Verify: `curl http://localhost:8000/health` → `{"status":"ok"}`

**Step 9: Commit**

```bash
cd ~/dev/mazkir
git add apps/vault-server/ --force  # --force because venv is usually gitignored
# Actually, add a .gitignore for venv first
echo "venv/" > apps/vault-server/.gitignore
git add apps/vault-server/
git commit -m "feat: scaffold vault-server FastAPI app"
```

---

### Task 8: Migrate vault_service.py to vault-server

**Files:**
- Create: `apps/vault-server/src/services/vault_service.py`

**Step 1: Copy vault_service.py**

```bash
cp ~/dev/mazkir/apps/telegram-py-client/src/services/vault_service.py \
   ~/dev/mazkir/apps/vault-server/src/services/vault_service.py
```

The file is self-contained (no imports from `src.config`). It only depends on `pathlib`, `datetime`, `frontmatter`, `pytz`, `re`, `shutil`. No changes needed.

**Step 2: Write a smoke test**

Create `apps/vault-server/tests/test_vault_service.py`:
```python
"""Smoke tests for VaultService."""
import pytest
from pathlib import Path
from src.services.vault_service import VaultService


def test_vault_service_initializes(tmp_path):
    """VaultService initializes with a valid vault path."""
    # Create minimal vault structure
    agents_md = tmp_path / "AGENTS.md"
    agents_md.write_text("# Agents")

    service = VaultService(tmp_path)
    assert service.vault_path == tmp_path


def test_vault_service_rejects_missing_path():
    """VaultService raises if vault path doesn't exist."""
    with pytest.raises(FileNotFoundError):
        VaultService(Path("/nonexistent/path"))
```

**Step 3: Run test**

```bash
cd ~/dev/mazkir/apps/vault-server
source venv/bin/activate
pytest tests/test_vault_service.py -v
```
Expected: 2 tests PASS

**Step 4: Commit**

```bash
cd ~/dev/mazkir
git add apps/vault-server/src/services/vault_service.py apps/vault-server/tests/test_vault_service.py
git commit -m "feat: migrate vault_service.py to vault-server"
```

---

### Task 9: Migrate claude_service.py to vault-server

**Files:**
- Create: `apps/vault-server/src/services/claude_service.py`

**Step 1: Copy claude_service.py**

```bash
cp ~/dev/mazkir/apps/telegram-py-client/src/services/claude_service.py \
   ~/dev/mazkir/apps/vault-server/src/services/claude_service.py
```

Self-contained — depends on `anthropic`, `datetime`, `pytz`. No changes needed.

**Step 2: Commit**

```bash
cd ~/dev/mazkir
git add apps/vault-server/src/services/claude_service.py
git commit -m "feat: migrate claude_service.py to vault-server"
```

---

### Task 10: Migrate calendar_service.py to vault-server

**Files:**
- Create: `apps/vault-server/src/services/calendar_service.py`

**Step 1: Copy calendar_service.py**

```bash
cp ~/dev/mazkir/apps/telegram-py-client/src/services/calendar_service.py \
   ~/dev/mazkir/apps/vault-server/src/services/calendar_service.py
```

Self-contained — depends on google API libs, httplib2, pytz. No changes needed.

**Step 2: Commit**

```bash
cd ~/dev/mazkir
git add apps/vault-server/src/services/calendar_service.py
git commit -m "feat: migrate calendar_service.py to vault-server"
```

---

### Task 11: Add API key auth middleware

**Files:**
- Create: `apps/vault-server/src/auth.py`

**Step 1: Create auth dependency**

Create `apps/vault-server/src/auth.py`:
```python
"""API key authentication."""
from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader
from src.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str | None = Security(api_key_header)):
    if not settings.api_key:
        return  # No auth configured, allow all
    if api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
```

**Step 2: Commit**

```bash
cd ~/dev/mazkir
git add apps/vault-server/src/auth.py
git commit -m "feat: add API key auth middleware"
```

---

### Task 12: Create service initialization in main.py

**Files:**
- Modify: `apps/vault-server/src/main.py`

**Step 1: Update main.py with service initialization and lifespan**

Replace `apps/vault-server/src/main.py` with:
```python
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

    # Initialize vault service
    vault = VaultService(settings.vault_path, settings.vault_timezone)
    logger.info(f"Vault service initialized: {settings.vault_path}")

    # Initialize Claude service
    if settings.anthropic_api_key:
        claude = ClaudeService(
            api_key=settings.anthropic_api_key,
            vault_path=str(settings.vault_path),
            timezone=settings.vault_timezone,
        )
        logger.info("Claude service initialized")

    # Initialize calendar service
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

    # Cleanup (nothing needed currently)


app = FastAPI(title="Mazkir Vault Server", version="0.1.0", lifespan=lifespan)


def get_vault() -> VaultService:
    assert vault is not None, "Vault service not initialized"
    return vault


def get_claude() -> ClaudeService | None:
    return claude


def get_calendar() -> CalendarService | None:
    return calendar


@app.get("/health")
async def health():
    return {"status": "ok", "vault": vault is not None}
```

**Step 2: Commit**

```bash
cd ~/dev/mazkir
git add apps/vault-server/src/main.py
git commit -m "feat: add service initialization with lifespan"
```

---

### Task 13: Create API routes — tasks

**Files:**
- Create: `apps/vault-server/src/api/routes/tasks.py`
- Modify: `apps/vault-server/src/main.py` (add router)

**Step 1: Create tasks router**

Create `apps/vault-server/src/api/routes/tasks.py`:
```python
"""Task API routes."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from src.main import get_vault, get_calendar
from src.auth import verify_api_key

router = APIRouter(prefix="/tasks", tags=["tasks"], dependencies=[Depends(verify_api_key)])


class TaskCreate(BaseModel):
    name: str
    priority: int = 3
    due_date: str | None = None
    category: str = "personal"
    tokens_on_completion: int = 5


class TaskComplete(BaseModel):
    completed: bool = True


@router.get("")
async def list_tasks():
    vault = get_vault()
    tasks = vault.list_active_tasks()
    return [
        {
            "name": t["metadata"].get("name", "Unnamed"),
            "priority": t["metadata"].get("priority", 3),
            "due_date": t["metadata"].get("due_date"),
            "category": t["metadata"].get("category", "personal"),
            "status": t["metadata"].get("status", "active"),
            "google_event_id": t["metadata"].get("google_event_id"),
            "path": t["path"],
        }
        for t in tasks
    ]


@router.post("", status_code=201)
async def create_task(body: TaskCreate):
    vault = get_vault()
    calendar = get_calendar()

    result = vault.create_task(
        name=body.name,
        priority=body.priority,
        due_date=body.due_date,
        category=body.category,
        tokens_on_completion=body.tokens_on_completion,
    )

    # Sync to calendar if enabled and task has due date
    if calendar and calendar.is_initialized and body.due_date:
        try:
            event_id = await calendar.sync_task(result)
            if event_id:
                vault.update_google_event_id(result["path"], event_id)
                result["metadata"]["google_event_id"] = event_id
        except Exception:
            pass  # Calendar sync is best-effort

    return {
        "name": result["metadata"]["name"],
        "priority": result["metadata"]["priority"],
        "due_date": result["metadata"].get("due_date"),
        "category": result["metadata"]["category"],
        "tokens_on_completion": result["metadata"].get("tokens_on_completion", 5),
        "path": result["path"],
        "google_event_id": result["metadata"].get("google_event_id"),
    }


@router.patch("/{name}")
async def complete_task(name: str, body: TaskComplete):
    vault = get_vault()
    calendar = get_calendar()

    if not body.completed:
        raise HTTPException(400, "Only completion is supported via PATCH")

    task = vault.find_task_by_name(name)
    if not task:
        raise HTTPException(404, f"Task not found: {name}")

    google_event_id = task["metadata"].get("google_event_id")
    result = vault.complete_task(task["path"])

    # Mark calendar event complete
    if calendar and calendar.is_initialized and google_event_id:
        try:
            await calendar.mark_event_complete(google_event_id)
        except Exception:
            pass

    return {
        "task_name": result["task_name"],
        "tokens_earned": result["tokens_earned"],
        "archive_path": result["archive_path"],
    }
```

**Step 2: Register router in main.py**

Add before the `@app.get("/health")` line in `apps/vault-server/src/main.py`:
```python
from src.api.routes.tasks import router as tasks_router
app.include_router(tasks_router)
```

**Step 3: Commit**

```bash
cd ~/dev/mazkir
git add apps/vault-server/src/api/routes/tasks.py apps/vault-server/src/main.py
git commit -m "feat: add tasks API routes"
```

---

### Task 14: Create API routes — habits

**Files:**
- Create: `apps/vault-server/src/api/routes/habits.py`
- Modify: `apps/vault-server/src/main.py` (add router)

**Step 1: Create habits router**

Create `apps/vault-server/src/api/routes/habits.py`:
```python
"""Habit API routes."""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import pytz
from src.main import get_vault, get_calendar
from src.auth import verify_api_key
from src.config import settings

router = APIRouter(prefix="/habits", tags=["habits"], dependencies=[Depends(verify_api_key)])

tz = pytz.timezone(settings.vault_timezone)


class HabitCreate(BaseModel):
    name: str
    frequency: str = "daily"
    category: str = "personal"
    difficulty: str = "medium"
    tokens_per_completion: int = 5


class HabitComplete(BaseModel):
    completed: bool = True


@router.get("")
async def list_habits():
    vault = get_vault()
    habits = vault.list_active_habits()

    today = datetime.now(tz).strftime("%Y-%m-%d")

    return [
        {
            "name": h["metadata"].get("name", "Unknown"),
            "frequency": h["metadata"].get("frequency", "daily"),
            "streak": h["metadata"].get("streak", 0),
            "longest_streak": h["metadata"].get("longest_streak", 0),
            "last_completed": h["metadata"].get("last_completed"),
            "completed_today": h["metadata"].get("last_completed") == today,
            "tokens_per_completion": h["metadata"].get("tokens_per_completion", 5),
            "path": h["path"],
        }
        for h in sorted(
            habits, key=lambda h: h["metadata"].get("streak", 0), reverse=True
        )
    ]


@router.post("", status_code=201)
async def create_habit(body: HabitCreate):
    vault = get_vault()
    calendar = get_calendar()

    result = vault.create_habit(
        name=body.name,
        frequency=body.frequency,
        category=body.category,
        difficulty=body.difficulty,
        tokens_per_completion=body.tokens_per_completion,
    )

    # Sync to calendar
    if calendar and calendar.is_initialized:
        try:
            event_id = await calendar.sync_habit(result)
            if event_id:
                vault.update_google_event_id(result["path"], event_id)
                result["metadata"]["google_event_id"] = event_id
        except Exception:
            pass

    return {
        "name": result["metadata"]["name"],
        "frequency": result["metadata"]["frequency"],
        "category": result["metadata"]["category"],
        "path": result["path"],
        "google_event_id": result["metadata"].get("google_event_id"),
    }


@router.patch("/{name}")
async def complete_habit(name: str, body: HabitComplete):
    vault = get_vault()
    calendar = get_calendar()

    if not body.completed:
        raise HTTPException(400, "Only completion is supported via PATCH")

    # Find matching habit
    habits = vault.list_active_habits()
    matched = None
    for h in habits:
        h_name = h["metadata"].get("name", "").lower()
        if name.lower() in h_name or h_name in name.lower():
            matched = h
            break

    if not matched:
        available = [h["metadata"].get("name") for h in habits]
        raise HTTPException(404, f"Habit not found: {name}. Available: {available}")

    meta = matched["metadata"]
    today = datetime.now(tz).strftime("%Y-%m-%d")

    # Check already completed
    if meta.get("last_completed") == today:
        return {
            "already_completed": True,
            "name": meta["name"],
            "streak": meta.get("streak", 0),
        }

    # Update streak
    new_streak = meta.get("streak", 0) + 1
    tokens_per = meta.get("tokens_per_completion", 5)

    vault.update_file(matched["path"], {
        "streak": new_streak,
        "last_completed": today,
        "longest_streak": max(meta.get("longest_streak", 0), new_streak),
    })

    token_result = vault.update_tokens(tokens_per, f"Completed {meta['name']}")

    # Mark calendar event complete
    google_event_id = meta.get("google_event_id")
    if calendar and calendar.is_initialized and google_event_id:
        try:
            await calendar.mark_event_complete(google_event_id, today)
        except Exception:
            pass

    return {
        "already_completed": False,
        "name": meta["name"],
        "old_streak": new_streak - 1,
        "new_streak": new_streak,
        "tokens_earned": tokens_per,
        "new_token_total": token_result["new_total"],
    }
```

**Step 2: Register router in main.py**

Add to imports and include:
```python
from src.api.routes.habits import router as habits_router
app.include_router(habits_router)
```

**Step 3: Commit**

```bash
cd ~/dev/mazkir
git add apps/vault-server/src/api/routes/habits.py apps/vault-server/src/main.py
git commit -m "feat: add habits API routes"
```

---

### Task 15: Create API routes — goals, daily, tokens

**Files:**
- Create: `apps/vault-server/src/api/routes/goals.py`
- Create: `apps/vault-server/src/api/routes/daily.py`
- Create: `apps/vault-server/src/api/routes/tokens.py`
- Modify: `apps/vault-server/src/main.py` (add routers)

**Step 1: Create goals router**

Create `apps/vault-server/src/api/routes/goals.py`:
```python
"""Goal API routes."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from src.main import get_vault
from src.auth import verify_api_key

router = APIRouter(prefix="/goals", tags=["goals"], dependencies=[Depends(verify_api_key)])


class GoalCreate(BaseModel):
    name: str
    priority: str = "medium"
    target_date: str | None = None
    category: str = "personal"


@router.get("")
async def list_goals():
    vault = get_vault()
    goals = vault.list_active_goals()
    return [
        {
            "name": g["metadata"].get("name", "Unnamed"),
            "status": g["metadata"].get("status", "unknown"),
            "priority": g["metadata"].get("priority", "medium"),
            "progress": g["metadata"].get("progress", 0),
            "target_date": g["metadata"].get("target_date"),
            "milestones": g["metadata"].get("milestones", []),
            "path": g["path"],
        }
        for g in goals
    ]


@router.post("", status_code=201)
async def create_goal(body: GoalCreate):
    vault = get_vault()
    result = vault.create_goal(
        name=body.name,
        priority=body.priority,
        target_date=body.target_date,
        category=body.category,
    )
    return {
        "name": result["metadata"]["name"],
        "priority": result["metadata"]["priority"],
        "target_date": result["metadata"].get("target_date"),
        "category": result["metadata"]["category"],
        "path": result["path"],
    }
```

**Step 2: Create daily router**

Create `apps/vault-server/src/api/routes/daily.py`:
```python
"""Daily note API routes."""
from datetime import datetime
from fastapi import APIRouter, Depends
import pytz
from src.main import get_vault, get_calendar
from src.auth import verify_api_key
from src.config import settings

router = APIRouter(prefix="/daily", tags=["daily"], dependencies=[Depends(verify_api_key)])

tz = pytz.timezone(settings.vault_timezone)


@router.get("")
async def get_daily():
    vault = get_vault()
    calendar = get_calendar()

    # Read or create daily note
    try:
        daily = vault.read_daily_note()
    except FileNotFoundError:
        daily = vault.create_daily_note()

    metadata = daily["metadata"]

    # Get habits status
    habits = vault.list_active_habits()
    completed_habits = metadata.get("completed_habits", [])
    today = datetime.now(tz).strftime("%Y-%m-%d")

    habit_status = []
    for h in habits:
        h_meta = h["metadata"]
        name = h_meta.get("name", "Unknown")
        habit_status.append({
            "name": name,
            "completed": name in completed_habits or h_meta.get("last_completed") == today,
            "streak": h_meta.get("streak", 0),
        })

    # Get calendar events
    calendar_events = []
    if calendar and calendar.is_initialized:
        try:
            events = await calendar.get_todays_events(all_calendars=True)
            calendar_events = events
        except Exception:
            pass

    return {
        "date": metadata.get("date"),
        "day_of_week": metadata.get("day_of_week"),
        "tokens_earned": metadata.get("tokens_earned", 0),
        "tokens_total": metadata.get("tokens_total", 0),
        "habits": habit_status,
        "calendar_events": calendar_events,
    }
```

**Step 3: Create tokens router**

Create `apps/vault-server/src/api/routes/tokens.py`:
```python
"""Token API routes."""
from fastapi import APIRouter, Depends
from src.main import get_vault
from src.auth import verify_api_key

router = APIRouter(prefix="/tokens", tags=["tokens"], dependencies=[Depends(verify_api_key)])


@router.get("")
async def get_tokens():
    vault = get_vault()
    ledger = vault.read_token_ledger()
    meta = ledger["metadata"]
    return {
        "total": meta.get("total_tokens", 0),
        "today": meta.get("tokens_today", 0),
        "all_time": meta.get("all_time_tokens", 0),
    }
```

**Step 4: Register all routers in main.py**

Add to `apps/vault-server/src/main.py`:
```python
from src.api.routes.goals import router as goals_router
from src.api.routes.daily import router as daily_router
from src.api.routes.tokens import router as tokens_router
app.include_router(goals_router)
app.include_router(daily_router)
app.include_router(tokens_router)
```

**Step 5: Commit**

```bash
cd ~/dev/mazkir
git add apps/vault-server/src/api/routes/goals.py \
       apps/vault-server/src/api/routes/daily.py \
       apps/vault-server/src/api/routes/tokens.py \
       apps/vault-server/src/main.py
git commit -m "feat: add goals, daily, and tokens API routes"
```

---

### Task 16: Create API routes — calendar and message

**Files:**
- Create: `apps/vault-server/src/api/routes/calendar.py`
- Create: `apps/vault-server/src/api/routes/message.py`
- Modify: `apps/vault-server/src/main.py` (add routers)

**Step 1: Create calendar router**

Create `apps/vault-server/src/api/routes/calendar.py`:
```python
"""Calendar API routes."""
import logging
from fastapi import APIRouter, Depends, HTTPException
from src.main import get_vault, get_calendar
from src.auth import verify_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calendar", tags=["calendar"], dependencies=[Depends(verify_api_key)])


@router.get("/events")
async def get_events():
    calendar = get_calendar()
    if not calendar or not calendar.is_initialized:
        raise HTTPException(503, "Calendar service not enabled")

    events = await calendar.get_todays_events(all_calendars=True)
    return events


@router.post("/sync")
async def sync_calendar():
    vault = get_vault()
    calendar = get_calendar()

    if not calendar or not calendar.is_initialized:
        raise HTTPException(503, "Calendar service not enabled")

    habits_synced = 0
    tasks_synced = 0
    errors = 0

    for habit in vault.get_habits_needing_sync():
        try:
            event_id = await calendar.sync_habit(habit)
            if event_id:
                vault.update_google_event_id(habit["path"], event_id)
                habits_synced += 1
            else:
                errors += 1
        except Exception as e:
            logger.error(f"Error syncing habit: {e}")
            errors += 1

    for task in vault.get_tasks_needing_sync():
        try:
            event_id = await calendar.sync_task(task)
            if event_id:
                vault.update_google_event_id(task["path"], event_id)
                tasks_synced += 1
            else:
                errors += 1
        except Exception as e:
            logger.error(f"Error syncing task: {e}")
            errors += 1

    return {
        "habits_synced": habits_synced,
        "tasks_synced": tasks_synced,
        "errors": errors,
    }
```

**Step 2: Create message router (NL endpoint)**

Create `apps/vault-server/src/api/routes/message.py`:
```python
"""Natural language message API route."""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import pytz
from src.main import get_vault, get_claude, get_calendar
from src.auth import verify_api_key
from src.config import settings

router = APIRouter(tags=["message"], dependencies=[Depends(verify_api_key)])

tz = pytz.timezone(settings.vault_timezone)


class MessageRequest(BaseModel):
    text: str


@router.post("/message")
async def handle_message(body: MessageRequest):
    vault = get_vault()
    claude = get_claude()
    calendar = get_calendar()

    if not claude:
        raise HTTPException(503, "Claude service not configured")

    # Get context for intent parsing
    habits = vault.list_active_habits()
    habit_names = [h["metadata"].get("name", "Unknown") for h in habits]
    tasks = vault.list_active_tasks()
    task_names = [t["metadata"].get("name", "") for t in tasks if t["metadata"].get("name")]

    # Parse intent
    intent_result = claude.parse_intent(body.text, habit_names, task_names)
    intent = intent_result.get("intent")
    data = intent_result.get("data", {})

    # Route to handler
    if intent == "HABIT_COMPLETION":
        return await _handle_habit_completion(data, vault, calendar)
    elif intent == "HABIT_CREATION":
        return await _handle_habit_creation(data, vault, calendar)
    elif intent == "TASK_CREATION":
        return await _handle_task_creation(data, vault, calendar)
    elif intent == "TASK_COMPLETION":
        return await _handle_task_completion(data, vault, calendar)
    elif intent == "GOAL_CREATION":
        return await _handle_goal_creation(data, vault)
    elif intent == "QUERY":
        return _handle_query(data, body.text, vault, claude)
    else:
        response = claude.chat(body.text)
        return {"intent": "GENERAL_CHAT", "response": response}


async def _handle_habit_completion(data, vault, calendar):
    habit_name = data.get("habit_name", "").lower()
    if not habit_name:
        return {"intent": "HABIT_COMPLETION", "error": "No habit name identified"}

    habits = vault.list_active_habits()
    matched = None
    for h in habits:
        h_name = h["metadata"].get("name", "").lower()
        if habit_name in h_name or h_name in habit_name:
            matched = h
            break

    if not matched:
        available = [h["metadata"].get("name") for h in habits]
        return {"intent": "HABIT_COMPLETION", "error": f"Not found: {habit_name}", "available": available}

    meta = matched["metadata"]
    today = datetime.now(tz).strftime("%Y-%m-%d")

    if meta.get("last_completed") == today:
        return {"intent": "HABIT_COMPLETION", "already_completed": True, "name": meta["name"], "streak": meta.get("streak", 0)}

    new_streak = meta.get("streak", 0) + 1
    tokens_per = meta.get("tokens_per_completion", 5)

    vault.update_file(matched["path"], {
        "streak": new_streak,
        "last_completed": today,
        "longest_streak": max(meta.get("longest_streak", 0), new_streak),
    })

    token_result = vault.update_tokens(tokens_per, f"Completed {meta['name']}")

    google_event_id = meta.get("google_event_id")
    if calendar and calendar.is_initialized and google_event_id:
        try:
            await calendar.mark_event_complete(google_event_id, today)
        except Exception:
            pass

    return {
        "intent": "HABIT_COMPLETION",
        "name": meta["name"],
        "old_streak": new_streak - 1,
        "new_streak": new_streak,
        "tokens_earned": tokens_per,
        "new_token_total": token_result["new_total"],
    }


async def _handle_habit_creation(data, vault, calendar):
    name = data.get("habit_name", "").strip()
    if not name:
        return {"intent": "HABIT_CREATION", "error": "No habit name"}

    result = vault.create_habit(
        name=name,
        frequency=data.get("frequency", "daily"),
        category=data.get("category", "personal"),
    )

    if calendar and calendar.is_initialized:
        try:
            event_id = await calendar.sync_habit(result)
            if event_id:
                vault.update_google_event_id(result["path"], event_id)
        except Exception:
            pass

    return {
        "intent": "HABIT_CREATION",
        "name": name,
        "frequency": data.get("frequency", "daily"),
        "path": result["path"],
    }


async def _handle_task_creation(data, vault, calendar):
    name = (data.get("task_name") or data.get("task_description", "")).strip()
    if not name:
        return {"intent": "TASK_CREATION", "error": "No task name"}

    priority = data.get("priority", 3)
    due_date = data.get("due_date")
    category = data.get("category", "personal")

    result = vault.create_task(
        name=name,
        priority=priority,
        due_date=due_date,
        category=category,
        tokens_on_completion=5 if priority <= 2 else 10 if priority <= 3 else 15,
    )

    if calendar and calendar.is_initialized and due_date:
        try:
            event_id = await calendar.sync_task(result)
            if event_id:
                vault.update_google_event_id(result["path"], event_id)
        except Exception:
            pass

    return {
        "intent": "TASK_CREATION",
        "name": name,
        "priority": priority,
        "due_date": due_date,
        "path": result["path"],
    }


async def _handle_task_completion(data, vault, calendar):
    task_name = data.get("task_name", "").strip()
    if not task_name:
        return {"intent": "TASK_COMPLETION", "error": "No task name"}

    task = vault.find_task_by_name(task_name)
    if not task:
        tasks = vault.list_active_tasks()
        names = [t["metadata"].get("name", "Unknown") for t in tasks[:5]]
        return {"intent": "TASK_COMPLETION", "error": f"Not found: {task_name}", "available": names}

    google_event_id = task["metadata"].get("google_event_id")
    result = vault.complete_task(task["path"])

    if calendar and calendar.is_initialized and google_event_id:
        try:
            await calendar.mark_event_complete(google_event_id)
        except Exception:
            pass

    return {
        "intent": "TASK_COMPLETION",
        "task_name": result["task_name"],
        "tokens_earned": result["tokens_earned"],
    }


async def _handle_goal_creation(data, vault):
    name = data.get("goal_name", "").strip()
    if not name:
        return {"intent": "GOAL_CREATION", "error": "No goal name"}

    result = vault.create_goal(
        name=name,
        priority=data.get("priority", "medium"),
        target_date=data.get("target_date"),
        category=data.get("category", "personal"),
    )

    return {
        "intent": "GOAL_CREATION",
        "name": name,
        "priority": data.get("priority", "medium"),
        "path": result["path"],
    }


def _handle_query(data, original_message, vault, claude):
    query_type = data.get("query_type", "general")

    if query_type == "streaks":
        habits = vault.list_active_habits()
        habits.sort(key=lambda h: h["metadata"].get("streak", 0), reverse=True)
        return {
            "intent": "QUERY",
            "query_type": "streaks",
            "data": [
                {"name": h["metadata"].get("name"), "streak": h["metadata"].get("streak", 0), "longest": h["metadata"].get("longest_streak", 0)}
                for h in habits[:10]
            ],
        }
    elif query_type == "tokens":
        ledger = vault.read_token_ledger()
        meta = ledger["metadata"]
        return {
            "intent": "QUERY",
            "query_type": "tokens",
            "data": {"total": meta.get("total_tokens", 0), "today": meta.get("tokens_today", 0), "all_time": meta.get("all_time_tokens", 0)},
        }
    else:
        response = claude.chat(original_message)
        return {"intent": "QUERY", "query_type": "general", "response": response}
```

**Step 3: Register routers in main.py**

Add to `apps/vault-server/src/main.py`:
```python
from src.api.routes.calendar import router as calendar_router
from src.api.routes.message import router as message_router
app.include_router(calendar_router)
app.include_router(message_router)
```

**Step 4: Commit**

```bash
cd ~/dev/mazkir
git add apps/vault-server/src/api/routes/calendar.py \
       apps/vault-server/src/api/routes/message.py \
       apps/vault-server/src/main.py
git commit -m "feat: add calendar and message API routes"
```

---

## Phase 5: Refactor Telegram Client

### Task 17: Create api_client.py for vault-server communication

**Files:**
- Create: `apps/telegram-py-client/src/api_client.py`

**Step 1: Create the API client**

Create `apps/telegram-py-client/src/api_client.py`:
```python
"""HTTP client for vault-server API."""
import httpx
import logging

logger = logging.getLogger(__name__)


class VaultAPIClient:
    """Client for communicating with vault-server."""

    def __init__(self, base_url: str = "http://localhost:8000", api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.headers = {}
        if api_key:
            self.headers["X-API-Key"] = api_key
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self.headers,
            timeout=30.0,
        )

    async def close(self):
        await self._client.aclose()

    # Daily
    async def get_daily(self) -> dict:
        r = await self._client.get("/daily")
        r.raise_for_status()
        return r.json()

    # Tasks
    async def list_tasks(self) -> list:
        r = await self._client.get("/tasks")
        r.raise_for_status()
        return r.json()

    async def create_task(self, **kwargs) -> dict:
        r = await self._client.post("/tasks", json=kwargs)
        r.raise_for_status()
        return r.json()

    async def complete_task(self, name: str) -> dict:
        r = await self._client.patch(f"/tasks/{name}", json={"completed": True})
        r.raise_for_status()
        return r.json()

    # Habits
    async def list_habits(self) -> list:
        r = await self._client.get("/habits")
        r.raise_for_status()
        return r.json()

    async def create_habit(self, **kwargs) -> dict:
        r = await self._client.post("/habits", json=kwargs)
        r.raise_for_status()
        return r.json()

    async def complete_habit(self, name: str) -> dict:
        r = await self._client.patch(f"/habits/{name}", json={"completed": True})
        r.raise_for_status()
        return r.json()

    # Goals
    async def list_goals(self) -> list:
        r = await self._client.get("/goals")
        r.raise_for_status()
        return r.json()

    async def create_goal(self, **kwargs) -> dict:
        r = await self._client.post("/goals", json=kwargs)
        r.raise_for_status()
        return r.json()

    # Tokens
    async def get_tokens(self) -> dict:
        r = await self._client.get("/tokens")
        r.raise_for_status()
        return r.json()

    # Calendar
    async def get_calendar_events(self) -> list:
        r = await self._client.get("/calendar/events")
        r.raise_for_status()
        return r.json()

    async def sync_calendar(self) -> dict:
        r = await self._client.post("/calendar/sync")
        r.raise_for_status()
        return r.json()

    # Message (NL)
    async def send_message(self, text: str) -> dict:
        r = await self._client.post("/message", json={"text": text})
        r.raise_for_status()
        return r.json()
```

**Step 2: Add httpx to telegram client requirements**

Append to `apps/telegram-py-client/requirements.txt`:
```
httpx>=0.27.0
```

**Step 3: Install httpx**

```bash
cd ~/dev/mazkir/apps/telegram-py-client
source venv/bin/activate
pip install httpx
```

**Step 4: Commit**

```bash
cd ~/dev/mazkir
git add apps/telegram-py-client/src/api_client.py apps/telegram-py-client/requirements.txt
git commit -m "feat: add vault-server API client to telegram app"
```

---

### Task 18: Rewrite handlers.py to use API client

**Files:**
- Rewrite: `apps/telegram-py-client/src/bot/handlers.py`

**Context:** This is the core refactoring. Replace all direct vault/claude/calendar service calls with `api_client` HTTP calls. All business logic moves out — handlers only format responses for Telegram.

**Step 1: Rewrite handlers.py**

Replace `apps/telegram-py-client/src/bot/handlers.py` with:
```python
"""Message and command handlers for the bot (thin client)."""
import logging
from telethon import events, Button
from dateutil import parser as dateutil_parser
from src.config import settings
from src.api_client import VaultAPIClient

logger = logging.getLogger(__name__)

# API client (initialized on import)
api = VaultAPIClient(
    base_url=settings.vault_server_url,
    api_key=settings.vault_server_api_key,
)


# Middleware: Only allow authorized user
def authorized_only(func):
    async def wrapper(event):
        if event.sender_id != settings.authorized_user_id:
            await event.respond("Unauthorized. This bot is for Marc's personal use only.")
            return
        return await func(event)
    return wrapper


@authorized_only
async def cmd_start(event):
    await event.respond(
        "**Welcome to Mazkir!**\n\n"
        "Your Personal AI Assistant for productivity and motivation.\n\n"
        "**Quick commands:**\n"
        "/day - Today's note\n"
        "/tasks - Active tasks\n"
        "/habits - Habit tracker\n"
        "/goals - Active goals\n"
        "/tokens - Token balance\n"
        "/help - Full command list\n\n"
        "**Or just chat naturally:**\n"
        '- "I completed gym" - Log a habit\n'
        '- "Create task: buy milk" - Add a task\n'
        '- "Done with groceries" - Complete a task'
    )
    raise events.StopPropagation


@authorized_only
async def cmd_day(event):
    try:
        data = await api.get_daily()

        day = data.get("day_of_week", "")
        date = data.get("date", "")
        response = f"**{day}, {date}**\n\n"

        response += f"**Tokens Today:** {data.get('tokens_earned', 0)}\n"
        response += f"**Total Bank:** {data.get('tokens_total', 0)} tokens\n\n"

        response += "**Daily Habits**\n"
        for h in data.get("habits", []):
            status = "done" if h["completed"] else "pending"
            streak_info = f" ({h['streak']} day streak)" if h["completed"] else ""
            response += f"- [{status}] {h['name']}{streak_info}\n"
        response += "\n"

        response += "**Tasks**\n_See /tasks for full list_\n\n"

        events_list = data.get("calendar_events", [])
        if events_list:
            response += "**Today's Schedule**\n"
            for evt in events_list:
                start_str = evt.get("start", "")
                if "T" in start_str:
                    start_time = dateutil_parser.parse(start_str)
                    time_fmt = start_time.strftime("%H:%M")
                else:
                    time_fmt = "All day"
                status = "done" if evt.get("completed") else "pending"
                summary = evt.get("summary", "Event")
                if summary.startswith("done "):
                    summary = summary[5:]
                cal_name = evt.get("calendar", "")
                if cal_name and cal_name != "Mazkir":
                    response += f"- [{status}] {time_fmt} - {summary} _({cal_name})_\n"
                else:
                    response += f"- [{status}] {time_fmt} - {summary}\n"

        await event.respond(response)
    except Exception as e:
        await event.respond(f"Error reading daily note: {str(e)}")

    raise events.StopPropagation


@authorized_only
async def cmd_tasks(event):
    try:
        tasks = await api.list_tasks()

        if not tasks:
            await event.respond("No active tasks! You're all caught up.")
            raise events.StopPropagation

        response = "**Active Tasks**\n\n"

        high = [t for t in tasks if t.get("priority", 3) >= 4]
        medium = [t for t in tasks if t.get("priority", 3) == 3]
        low = [t for t in tasks if t.get("priority", 3) <= 2]

        if high:
            response += "**High Priority**\n"
            for t in high:
                response += f"- {t['name']}\n"
            response += "\n"
        if medium:
            response += "**Medium Priority**\n"
            for t in medium:
                response += f"- {t['name']}\n"
            response += "\n"
        if low:
            response += "**Low Priority**\n"
            for t in low:
                response += f"- {t['name']}\n"
            response += "\n"

        response += f"---\nTotal: {len(tasks)} active tasks"
        await event.respond(response)
    except Exception as e:
        await event.respond(f"Error loading tasks: {str(e)}")

    raise events.StopPropagation


@authorized_only
async def cmd_habits(event):
    try:
        habits = await api.list_habits()

        if not habits:
            await event.respond("No active habits yet. Create one to get started!")
            raise events.StopPropagation

        response = "**Habit Tracker**\n\n**Active Streaks**\n"

        for h in habits:
            status = "done" if h.get("completed_today") else "pending"
            response += f"[{status}] {h['name']}: {h['streak']} days"
            if h.get("completed_today"):
                response += " (today)"
            response += "\n"
        response += "\n"

        total_streaks = sum(h.get("streak", 0) for h in habits)
        avg = total_streaks / len(habits) if habits else 0
        response += f"**Stats**\nTotal habits: {len(habits)}\nAverage streak: {avg:.1f} days"

        await event.respond(response)
    except Exception as e:
        await event.respond(f"Error loading habits: {str(e)}")

    raise events.StopPropagation


@authorized_only
async def cmd_goals(event):
    try:
        goals = await api.list_goals()

        if not goals:
            await event.respond("No active goals! Use /help to see how to create goals.")
            raise events.StopPropagation

        response = "**Active Goals**\n\n"

        for g in goals:
            priority = g.get("priority", "medium")
            progress = g.get("progress", 0)
            progress_bars = int(progress / 10)
            progress_bar = "=" * progress_bars + "-" * (10 - progress_bars)

            response += f"**{g['name']}**\n"
            response += f"Status: {g.get('status', 'unknown')}\n"
            response += f"Progress: [{progress_bar}] {progress}%\n"

            target = g.get("target_date")
            if target:
                response += f"Target: {target}\n"
            response += "\n"

        response += f"---\nTotal: {len(goals)} active goals"
        await event.respond(response)
    except Exception as e:
        await event.respond(f"Error loading goals: {str(e)}")

    raise events.StopPropagation


@authorized_only
async def cmd_tokens(event):
    try:
        data = await api.get_tokens()

        response = "**Motivation Tokens**\n\n"
        response += f"**Current Balance:** {data['total']} tokens\n"
        response += f"**Today's Earnings:** +{data['today']} tokens\n"
        response += f"**All Time:** {data['all_time']} tokens\n\n"

        next_milestone = ((data["total"] // 50) + 1) * 50
        needed = next_milestone - data["total"]
        response += f"**Next Milestone:** {next_milestone} tokens"
        if needed > 0:
            response += f" ({needed} tokens away!)"

        await event.respond(response)
    except Exception as e:
        await event.respond(f"Error loading tokens: {str(e)}")

    raise events.StopPropagation


@authorized_only
async def cmd_calendar(event):
    try:
        events_list = await api.get_calendar_events()

        if not events_list:
            await event.respond("**Today's Schedule**\n\nNo events scheduled for today.")
            raise events.StopPropagation

        response = "**Today's Schedule**\n\n"
        for evt in events_list:
            start_str = evt.get("start", "")
            if "T" in start_str:
                start_time = dateutil_parser.parse(start_str)
                time_fmt = start_time.strftime("%H:%M")
            else:
                time_fmt = "All day"
            status = "done" if evt.get("completed") else "pending"
            summary = evt.get("summary", "Event")
            cal_name = evt.get("calendar", "")
            if cal_name and cal_name != "Mazkir":
                response += f"[{status}] **{time_fmt}** - {summary} _({cal_name})_\n"
            else:
                response += f"[{status}] **{time_fmt}** - {summary}\n"

        completed = sum(1 for e in events_list if e.get("completed"))
        response += f"\n---\nCompleted: {completed}/{len(events_list)}"

        await event.respond(response)
    except Exception as e:
        if "503" in str(e):
            await event.respond("**Calendar not enabled**\n\nCalendar sync is disabled on the server.")
        else:
            await event.respond(f"Error loading calendar: {str(e)}")

    raise events.StopPropagation


@authorized_only
async def cmd_sync_calendar(event):
    try:
        await event.respond("Syncing to Google Calendar...")
        result = await api.sync_calendar()

        response = "**Calendar Sync Complete**\n\n"
        response += f"Habits synced: {result['habits_synced']}\n"
        response += f"Tasks synced: {result['tasks_synced']}\n"
        if result.get("errors", 0) > 0:
            response += f"Errors: {result['errors']}\n"

        await event.respond(response)
    except Exception as e:
        if "503" in str(e):
            await event.respond("**Calendar not enabled**\n\nCalendar sync is disabled on the server.")
        else:
            await event.respond(f"Error syncing calendar: {str(e)}")

    raise events.StopPropagation


@authorized_only
async def cmd_help(event):
    await event.respond(
        "**Mazkir Bot Commands**\n\n"
        "**Quick Access**\n"
        "/day - Today's daily note\n"
        "/tasks - Your active tasks\n"
        "/habits - Habit tracker\n"
        "/goals - Active goals\n"
        "/tokens - Token balance\n"
        "/calendar - Today's schedule\n"
        "/sync_calendar - Sync all items to calendar\n\n"
        "**Natural Language**\n"
        "Just chat naturally! Examples:\n\n"
        "_Complete activities:_\n"
        '- "I completed gym"\n'
        '- "Done with buy groceries"\n\n'
        "_Create items:_\n"
        '- "Create task: buy milk"\n'
        '- "Create habit: morning run"\n'
        '- "Create goal: learn python"'
    )
    raise events.StopPropagation


@authorized_only
async def handle_message(event):
    if event.message.text.startswith("/"):
        return

    try:
        async with event.client.action(event.chat_id, "typing"):
            result = await api.send_message(event.message.text)
            intent = result.get("intent", "GENERAL_CHAT")

            response = _format_nl_response(intent, result)
            await event.respond(response)
    except Exception as e:
        logger.error(f"Error in NL handler: {e}", exc_info=True)
        await event.respond(f"Sorry, I encountered an error: {str(e)}")

    raise events.StopPropagation


def _format_nl_response(intent: str, data: dict) -> str:
    """Format vault-server NL response for Telegram display."""
    if data.get("error"):
        available = data.get("available", [])
        msg = f"Error: {data['error']}"
        if available:
            msg += f"\n\nAvailable: {', '.join(str(a) for a in available)}"
        return msg

    if intent == "HABIT_COMPLETION":
        if data.get("already_completed"):
            return f"You already completed **{data['name']}** today! Streak: {data['streak']} days"
        response = f"Excellent! **{data['name']}** completed!\n\n"
        response += f"Streak: {data['old_streak']} -> **{data['new_streak']} days**\n"
        response += f"Tokens: +{data['tokens_earned']}\n"
        response += f"New balance: **{data['new_token_total']} tokens**"
        streak = data["new_streak"]
        if streak == 7:
            response += "\n\nOne week streak! Keep it up!"
        elif streak == 30:
            response += "\n\n30 days! Solid habit!"
        elif streak == 100:
            response += "\n\n100 days! Legendary!"
        elif streak % 10 == 0:
            response += f"\n\n{streak} days! On fire!"
        return response

    elif intent == "HABIT_CREATION":
        return f"Habit created: **{data['name']}**\nFrequency: {data.get('frequency', 'daily')}\n\nUse /habits to view your tracker."

    elif intent == "TASK_CREATION":
        priority_label = {5: "High", 4: "High", 3: "Medium", 2: "Low", 1: "Low"}.get(data.get("priority", 3), "Medium")
        response = f"Task created: **{data['name']}**\nPriority: {priority_label}\n"
        if data.get("due_date"):
            response += f"Due: {data['due_date']}\n"
        response += "\nUse /tasks to view all active tasks."
        return response

    elif intent == "TASK_COMPLETION":
        response = f"Task completed: **{data['task_name']}**\n"
        if data.get("tokens_earned", 0) > 0:
            response += f"Tokens earned: +{data['tokens_earned']}\n"
        response += "\nUse /tasks to see remaining tasks."
        return response

    elif intent == "GOAL_CREATION":
        response = f"Goal created: **{data['name']}**\n"
        response += f"Priority: {data.get('priority', 'medium')}\n"
        response += "\nUse /goals to view your active goals."
        return response

    elif intent == "QUERY":
        if data.get("query_type") == "streaks":
            lines = ["**Your Habit Streaks**\n"]
            for h in data.get("data", []):
                lines.append(f"- **{h['name']}**: {h['streak']} days (best: {h['longest']})")
            return "\n".join(lines)
        elif data.get("query_type") == "tokens":
            d = data.get("data", {})
            return f"**Token Balance**\n\nCurrent: **{d.get('total', 0)} tokens**\nToday: +{d.get('today', 0)}\nAll time: {d.get('all_time', 0)}"
        else:
            return data.get("response", "I don't have an answer for that.")

    else:
        return data.get("response", "I'm not sure how to help with that.")


def get_handlers():
    return [
        (cmd_start, events.NewMessage(pattern="/start")),
        (cmd_day, events.NewMessage(pattern="/day")),
        (cmd_tasks, events.NewMessage(pattern="/tasks")),
        (cmd_habits, events.NewMessage(pattern="/habits")),
        (cmd_goals, events.NewMessage(pattern="/goals")),
        (cmd_tokens, events.NewMessage(pattern="/tokens")),
        (cmd_calendar, events.NewMessage(pattern="/calendar")),
        (cmd_sync_calendar, events.NewMessage(pattern="/sync_calendar")),
        (cmd_help, events.NewMessage(pattern="/help")),
        (handle_message, events.NewMessage()),  # Must be last
    ]
```

**Step 2: Commit**

```bash
cd ~/dev/mazkir
git add apps/telegram-py-client/src/bot/handlers.py
git commit -m "refactor: rewrite handlers to use vault-server API client"
```

---

### Task 19: Update telegram client config and main.py

**Files:**
- Modify: `apps/telegram-py-client/src/config.py`
- Modify: `apps/telegram-py-client/src/main.py`

**Step 1: Simplify config.py**

Replace `apps/telegram-py-client/src/config.py` with:
```python
"""Telegram client configuration."""
import os
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

    # Telegram
    telegram_api_id: int
    telegram_api_hash: str
    telegram_bot_token: str
    telegram_phone: str = ""  # Kept for backwards compatibility

    # Vault Server
    vault_server_url: str = os.getenv("VAULT_SERVER_URL", "http://localhost:8000")
    vault_server_api_key: str = os.getenv("VAULT_SERVER_API_KEY", "")

    # Security
    authorized_user_id: int = int(os.getenv("AUTHORIZED_USER_ID", "0"))

    # Application
    log_level: str = "INFO"

    def validate_config(self):
        assert self.telegram_api_id, "TELEGRAM_API_ID required"
        assert self.telegram_api_hash, "TELEGRAM_API_HASH required"
        assert self.telegram_bot_token, "TELEGRAM_BOT_TOKEN required"
        assert self.authorized_user_id > 0, "AUTHORIZED_USER_ID required"


settings = Settings()
```

**Step 2: Simplify main.py**

Replace `apps/telegram-py-client/src/main.py` with:
```python
"""Main entry point for Mazkir Telegram client."""
import asyncio
import logging
from telethon import TelegramClient
from src.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    try:
        settings.validate_config()
    except AssertionError as e:
        logger.error(f"Configuration error: {e}")
        return

    logger.info("Starting Mazkir Telegram client...")

    from src.bot.handlers import get_handlers

    client = TelegramClient(
        "mazkir_bot_session",
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )

    handlers = get_handlers()
    for handler_func, event_builder in handlers:
        client.add_event_handler(handler_func, event_builder)

    await client.start(bot_token=settings.telegram_bot_token)

    me = await client.get_me()
    logger.info(f"Bot started: @{me.username}")
    logger.info(f"Vault server: {settings.vault_server_url}")
    logger.info(f"Authorized user: {settings.authorized_user_id}")

    print(f"\nMazkir Telegram client running as @{me.username}")
    print(f"Vault server: {settings.vault_server_url}")
    print("Press Ctrl+C to stop\n")

    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
```

**Step 3: Update .env.example**

Replace `apps/telegram-py-client/.env.example` with:
```
# Telegram Configuration
TELEGRAM_API_ID=your_api_id_here
TELEGRAM_API_HASH=your_api_hash_here
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_PHONE=+1234567890

# Vault Server
VAULT_SERVER_URL=http://localhost:8000
VAULT_SERVER_API_KEY=your_shared_secret_here

# Security
AUTHORIZED_USER_ID=your_telegram_user_id_here

# Application
LOG_LEVEL=INFO
```

**Step 4: Add VAULT_SERVER_URL and VAULT_SERVER_API_KEY to actual .env**

Edit `apps/telegram-py-client/.env` and add:
```
VAULT_SERVER_URL=http://localhost:8000
VAULT_SERVER_API_KEY=
```

**Step 5: Commit**

```bash
cd ~/dev/mazkir
git add apps/telegram-py-client/src/config.py \
       apps/telegram-py-client/src/main.py \
       apps/telegram-py-client/.env.example
git commit -m "refactor: simplify telegram client config (vault-server handles business logic)"
```

---

### Task 20: Remove migrated services and legacy code from telegram client

**Files:**
- Delete: `apps/telegram-py-client/src/services/vault_service.py`
- Delete: `apps/telegram-py-client/src/services/claude_service.py`
- Delete: `apps/telegram-py-client/src/services/calendar_service.py`
- Delete: `apps/telegram-py-client/src/services/llm_service.py`
- Delete: `apps/telegram-py-client/src/services/embedding_service.py`
- Delete: `apps/telegram-py-client/src/services/message_ingestion.py`
- Delete: `apps/telegram-py-client/src/database/` (entire directory)

**Step 1: Remove migrated services**

```bash
cd ~/dev/mazkir/apps/telegram-py-client
rm src/services/vault_service.py
rm src/services/claude_service.py
rm src/services/calendar_service.py
rm src/services/llm_service.py
rm src/services/embedding_service.py
rm src/services/message_ingestion.py
rm -rf src/database/
```

**Step 2: Clean up services __init__.py**

`apps/telegram-py-client/src/services/__init__.py` should be empty (or remove the directory entirely if no services remain).

**Step 3: Trim requirements.txt**

Replace `apps/telegram-py-client/requirements.txt` with:
```
# Telegram
telethon>=1.34.0

# HTTP client for vault-server
httpx>=0.27.0

# Configuration
python-dotenv>=1.0.0
pydantic>=2.5.0
pydantic-settings>=2.1.0

# Date parsing (used in response formatting)
python-dateutil>=2.8.2
```

**Step 4: Commit**

```bash
cd ~/dev/mazkir
git add -A apps/telegram-py-client/
git commit -m "refactor: remove migrated services and legacy database code from telegram client"
```

---

## Phase 6: Configuration & Cleanup

### Task 21: Update CLAUDE.md for new monorepo structure

**Files:**
- Rewrite: `~/dev/mazkir/CLAUDE.md`

**Step 1: Rewrite CLAUDE.md**

Update to reflect the new monorepo structure, apps, and development workflows. Key changes:
- Repository structure shows `apps/telegram-py-client/` and `apps/vault-server/`
- `memory/` replaces `~/pkm/` references
- Quick commands updated for new paths
- Development guidelines updated for the two-app architecture
- Remove references to `~/dev/tg-mazkir/`

**Step 2: Commit**

```bash
cd ~/dev/mazkir
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for monorepo structure"
```

---

### Task 22: Add .gitignore entries for Python/Node artifacts

**Files:**
- Modify: `~/dev/mazkir/.gitignore`

**Step 1: Create comprehensive .gitignore**

Ensure the root `.gitignore` includes:
```
# Vault (nested git repo)
memory/

# Node
node_modules/

# Python
__pycache__/
*.py[cod]
*.egg-info/
dist/
build/
venv/
.venv/

# IDE
.vscode/
.idea/

# Environment
.env
*.session

# OS
.DS_Store
```

**Step 2: Commit**

```bash
cd ~/dev/mazkir
git add .gitignore
git commit -m "chore: update .gitignore for monorepo"
```

---

### Task 23: End-to-end verification

**Step 1: Start vault-server**

```bash
cd ~/dev/mazkir/apps/vault-server
source venv/bin/activate
# Create .env from .env.example with real values (copy from telegram client's old .env)
python -m uvicorn src.main:app --port 8000
```

Expected: Server starts, vault service initializes, health check responds.

**Step 2: Test vault-server endpoints**

```bash
# Health
curl http://localhost:8000/health

# Tasks
curl http://localhost:8000/tasks

# Habits
curl http://localhost:8000/habits

# Daily
curl http://localhost:8000/daily

# Tokens
curl http://localhost:8000/tokens
```

Expected: All return JSON with real vault data.

**Step 3: Start telegram client** (in another terminal)

```bash
cd ~/dev/mazkir/apps/telegram-py-client
source venv/bin/activate
python -m src.main
```

Expected: Bot starts and connects.

**Step 4: Test commands via Telegram**

Send to the bot:
- `/day` — should show daily note
- `/tasks` — should show tasks
- `/habits` — should show habits
- "I completed gym" — should process NL via vault-server
- "Create task: test migration" — should create task

**Step 5: Verify vault symlink**

```bash
ls ~/pkm/AGENTS.md  # Should resolve via symlink
```

---

### Task 24: Final commit with all changes

**Step 1: Review all changes**

```bash
cd ~/dev/mazkir
git status
git diff --stat
```

**Step 2: Push to remote**

```bash
git push origin master
```

---

## Summary

| Phase | Tasks | Description |
|-------|-------|-------------|
| 1 | 1 | Rename GitHub repos, update remotes |
| 2 | 2-4 | Turborepo skeleton, move bot to apps/, merge docs |
| 3 | 5-6 | Move vault to memory/, create symlink, rename dir |
| 4 | 7-16 | Build vault-server (scaffold, migrate services, API routes) |
| 5 | 17-20 | Refactor telegram client (API client, rewrite handlers, cleanup) |
| 6 | 21-24 | Update docs, .gitignore, end-to-end verification |

**Total: 24 tasks**
