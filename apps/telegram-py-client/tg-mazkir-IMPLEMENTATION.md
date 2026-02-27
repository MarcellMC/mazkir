# tg-mazkir Implementation Guide

**Version:** 2.0  
**Target:** Telegram Bot for Mazkir PKM  
**Phase:** 1 - Core Commands  

---

## Quick Start for Claude Code

This document provides detailed implementation specifications for repurposing tg-mazkir as a Telegram interface for the Mazkir PKM system.

**Prerequisites:**
- Read `AGENTS.md` first (architecture overview)
- Vault reorganization complete
- AGENTS.md in vault at `/home/marcellmc/pkm/AGENTS.md`

---

## Phase 1: Core Bot Commands

### Step 1: Update Dependencies

**File:** `requirements.txt`

```txt
# Existing (keep)
telethon>=1.34.0
sqlalchemy[asyncio]>=2.0.0
asyncpg>=0.29.0
alembic>=1.13.0
python-dotenv>=1.0.0
aiofiles>=23.2.1

# New additions for v2.0
anthropic>=0.18.0           # Claude API
python-frontmatter>=1.0.0   # Parse YAML frontmatter
python-dateutil>=2.8.2      # Date parsing
pytz>=2024.1                # Timezone support

# Remove (not needed for v2.0)
# langchain
# langchain-anthropic
# chromadb
```

### Step 2: Update Configuration

**File:** `src/config.py`

```python
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

class Config:
    """Application configuration"""
    
    # Telegram
    TELEGRAM_API_ID = int(os.getenv('TELEGRAM_API_ID'))
    TELEGRAM_API_HASH = os.getenv('TELEGRAM_API_HASH')
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    TELEGRAM_PHONE = os.getenv('TELEGRAM_PHONE')
    
    # Claude API
    ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
    CLAUDE_MODEL = "claude-sonnet-4-20250514"
    CLAUDE_MAX_TOKENS = 4000
    
    # Vault
    VAULT_PATH = Path(os.getenv('VAULT_PATH', '/home/marcellmc/pkm'))
    VAULT_TIMEZONE = os.getenv('VAULT_TIMEZONE', 'Asia/Jerusalem')
    
    # Database
    DATABASE_URL = os.getenv('DATABASE_URL', 
        'postgresql+asyncpg://mazkir:mazkir_dev_password@localhost:5432/mazkir')
    
    # Features
    ENABLE_WEBAPP = os.getenv('ENABLE_WEBAPP', 'true').lower() == 'true'
    ENABLE_NOTIFICATIONS = os.getenv('ENABLE_NOTIFICATIONS', 'true').lower() == 'true'
    DEBUG = os.getenv('DEBUG', 'false').lower() == 'true'
    
    # Authorized users (for now, just Marc)
    AUTHORIZED_USER_ID = int(os.getenv('AUTHORIZED_USER_ID', '0'))
    
    @classmethod
    def validate(cls):
        """Validate required configuration"""
        assert cls.TELEGRAM_API_ID, "TELEGRAM_API_ID required"
        assert cls.TELEGRAM_API_HASH, "TELEGRAM_API_HASH required"
        assert cls.ANTHROPIC_API_KEY, "ANTHROPIC_API_KEY required"
        assert cls.VAULT_PATH.exists(), f"Vault not found at {cls.VAULT_PATH}"
        assert cls.AUTHORIZED_USER_ID > 0, "AUTHORIZED_USER_ID required"

config = Config()
```

### Step 3: Create Vault Service

**File:** `src/services/vault_service.py`

```python
from pathlib import Path
from datetime import datetime
import frontmatter
import pytz
from typing import Dict, List, Optional

class VaultService:
    """Service for reading and writing to Obsidian vault"""
    
    def __init__(self, vault_path: Path, timezone: str = "Asia/Jerusalem"):
        self.vault_path = Path(vault_path)
        self.tz = pytz.timezone(timezone)
        
        # Verify vault exists
        if not self.vault_path.exists():
            raise FileNotFoundError(f"Vault not found: {vault_path}")
        
        # Verify AGENTS.md exists
        agents_md = self.vault_path / "AGENTS.md"
        if not agents_md.exists():
            raise FileNotFoundError("AGENTS.md not found in vault")
    
    def read_file(self, relative_path: str) -> Dict:
        """Read a markdown file and parse frontmatter
        
        Args:
            relative_path: Path relative to vault root (e.g., "10-daily/2026-01-07.md")
            
        Returns:
            Dict with 'metadata' (frontmatter) and 'content' (body)
        """
        file_path = self.vault_path / relative_path
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {relative_path}")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            post = frontmatter.load(f)
        
        return {
            'metadata': dict(post.metadata),
            'content': post.content,
            'path': relative_path
        }
    
    def write_file(self, relative_path: str, metadata: Dict, content: str):
        """Write a markdown file with frontmatter
        
        Args:
            relative_path: Path relative to vault root
            metadata: Dictionary of frontmatter fields
            content: Markdown body content
        """
        file_path = self.vault_path / relative_path
        
        # Ensure directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Always update 'updated' timestamp
        metadata['updated'] = datetime.now(self.tz).strftime('%Y-%m-%d')
        
        # Create frontmatter post
        post = frontmatter.Post(content, **metadata)
        
        # Write to file
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(frontmatter.dumps(post))
    
    def update_file(self, relative_path: str, metadata_updates: Dict):
        """Update frontmatter of existing file
        
        Args:
            relative_path: Path relative to vault root
            metadata_updates: Dictionary of fields to update
        """
        # Read existing
        file_data = self.read_file(relative_path)
        
        # Update metadata
        file_data['metadata'].update(metadata_updates)
        
        # Write back
        self.write_file(relative_path, file_data['metadata'], file_data['content'])
    
    def list_files(self, directory: str, pattern: str = "*.md") -> List[Path]:
        """List files in a directory
        
        Args:
            directory: Directory relative to vault root
            pattern: Glob pattern for files
            
        Returns:
            List of Path objects relative to vault root
        """
        dir_path = self.vault_path / directory
        
        if not dir_path.exists():
            return []
        
        files = list(dir_path.glob(pattern))
        
        # Return paths relative to vault root
        return [f.relative_to(self.vault_path) for f in files]
    
    # Convenience methods for common operations
    
    def get_daily_note_path(self, date: Optional[datetime] = None) -> str:
        """Get path to daily note for given date"""
        if date is None:
            date = datetime.now(self.tz)
        return f"10-daily/{date.strftime('%Y-%m-%d')}.md"
    
    def read_daily_note(self, date: Optional[datetime] = None) -> Dict:
        """Read daily note for given date"""
        path = self.get_daily_note_path(date)
        return self.read_file(path)
    
    def read_habit(self, habit_name: str) -> Dict:
        """Read habit file
        
        Args:
            habit_name: Name of habit (e.g., 'gym-workout')
        """
        return self.read_file(f"20-habits/{habit_name}.md")
    
    def update_habit(self, habit_name: str, updates: Dict) -> Dict:
        """Update habit file and return updated data"""
        path = f"20-habits/{habit_name}.md"
        self.update_file(path, updates)
        return self.read_file(path)
    
    def list_active_habits(self) -> List[Dict]:
        """Get all active habits with their data"""
        habit_files = self.list_files("20-habits")
        habits = []
        
        for file_path in habit_files:
            data = self.read_file(str(file_path))
            if data['metadata'].get('status') == 'active':
                habits.append(data)
        
        return habits
    
    def list_active_tasks(self) -> List[Dict]:
        """Get all active tasks"""
        task_files = self.list_files("40-tasks/active")
        tasks = []
        
        for file_path in task_files:
            data = self.read_file(str(file_path))
            tasks.append(data)
        
        # Sort by priority (high to low) then due_date
        def sort_key(task):
            priority = task['metadata'].get('priority', 3)
            due_date = task['metadata'].get('due_date', '9999-12-31')
            return (-priority, due_date)
        
        return sorted(tasks, key=sort_key)
    
    def read_token_ledger(self) -> Dict:
        """Read motivation tokens ledger"""
        return self.read_file("00-system/motivation-tokens.md")
    
    def update_tokens(self, tokens_earned: int, activity: str) -> Dict:
        """Award tokens and update ledger
        
        Args:
            tokens_earned: Amount of tokens to award
            activity: Description of activity
            
        Returns:
            Updated token data
        """
        # Read current ledger
        ledger = self.read_token_ledger()
        metadata = ledger['metadata']
        
        # Update totals
        old_total = metadata.get('total_tokens', 0)
        new_total = old_total + tokens_earned
        tokens_today = metadata.get('tokens_today', 0) + tokens_earned
        
        # Update metadata
        updates = {
            'total_tokens': new_total,
            'tokens_today': tokens_today,
            'all_time_tokens': metadata.get('all_time_tokens', 0) + tokens_earned
        }
        
        self.update_file("00-system/motivation-tokens.md", updates)
        
        # Add transaction to today's daily note
        now = datetime.now(self.tz)
        try:
            daily = self.read_daily_note()
            daily_metadata = daily['metadata']
            
            daily_updates = {
                'tokens_earned': daily_metadata.get('tokens_earned', 0) + tokens_earned,
                'tokens_total': new_total
            }
            
            self.update_file(self.get_daily_note_path(), daily_updates)
        except FileNotFoundError:
            # Daily note doesn't exist yet - that's okay
            pass
        
        return {
            'tokens_earned': tokens_earned,
            'old_total': old_total,
            'new_total': new_total,
            'activity': activity
        }
```

### Step 4: Create Claude Service

**File:** `src/services/claude_service.py`

```python
import anthropic
from datetime import datetime
import pytz
from typing import List, Dict

class ClaudeService:
    """Service for interacting with Claude API"""
    
    def __init__(self, api_key: str, vault_path: str, timezone: str = "Asia/Jerusalem"):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.vault_path = vault_path
        self.tz = pytz.timezone(timezone)
        
        # Read AGENTS.md from vault for context
        agents_md_path = f"{vault_path}/AGENTS.md"
        try:
            with open(agents_md_path, 'r', encoding='utf-8') as f:
                self.vault_docs = f.read()
        except FileNotFoundError:
            self.vault_docs = "AGENTS.md not found"
    
    def build_system_prompt(self, context: Dict = None) -> str:
        """Build system prompt with vault context"""
        now = datetime.now(self.tz)
        
        base_prompt = f"""You are Marc's Personal AI Assistant with access to his Obsidian vault.

Current date: {now.strftime('%Y-%m-%d')}
Current time: {now.strftime('%H:%M')}
Day of week: {now.strftime('%A')}
Timezone: {self.tz.zone}

Vault location: {self.vault_path}

# Vault Documentation

{self.vault_docs}

# Your Capabilities

You can help Marc with:
- Tracking habits and building streaks
- Managing tasks and goals
- Awarding motivation tokens
- Creating and updating daily notes
- Providing progress reports and insights
- Answering questions about his vault data

# Important Guidelines

1. Be encouraging and supportive
2. Use emojis appropriately (💪🎯📖🧘🪙)
3. Be concise - Marc is busy
4. Show streaks, totals, and progress
5. Suggest next actions
6. NEVER delete user data without explicit confirmation
7. ALWAYS update the 'updated' field when modifying files

When Marc completes an activity:
1. Identify the type (habit/task/goal)
2. Calculate tokens earned (see token values in AGENTS.md)
3. Update the relevant files
4. Respond with encouragement + stats
"""
        
        if context:
            base_prompt += f"\n\n# Additional Context\n\n{context}\n"
        
        return base_prompt
    
    def chat(self, message: str, context: Dict = None) -> str:
        """Send message to Claude and get response
        
        Args:
            message: User's message
            context: Optional context dictionary
            
        Returns:
            Claude's response as text
        """
        system_prompt = self.build_system_prompt(context)
        
        response = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            system=system_prompt,
            messages=[{
                "role": "user",
                "content": message
            }]
        )
        
        return response.content[0].text
    
    def process_completion(self, activity: str) -> Dict:
        """Process activity completion and determine actions
        
        Args:
            activity: Description of completed activity
            
        Returns:
            Dict with 'response' (text) and 'actions' (list of dicts)
        """
        # This is a simplified version
        # In practice, Claude would parse the activity and return structured data
        
        message = f"I completed: {activity}"
        response = self.chat(message)
        
        return {
            'response': response,
            'actions': []  # Parse actions from response if needed
        }
```

### Step 5: Create Command Handlers

**File:** `src/bot/handlers.py`

```python
from telethon import events, Button
from datetime import datetime
import pytz
from src.config import config
from src.services.vault_service import VaultService
from src.services.claude_service import ClaudeService

# Initialize services
vault = VaultService(config.VAULT_PATH, config.VAULT_TIMEZONE)
claude = ClaudeService(
    api_key=config.ANTHROPIC_API_KEY,
    vault_path=str(config.VAULT_PATH),
    timezone=config.VAULT_TIMEZONE
)
tz = pytz.timezone(config.VAULT_TIMEZONE)


# Middleware: Only allow authorized user
def authorized_only(func):
    """Decorator to restrict commands to authorized user"""
    async def wrapper(event):
        if event.sender_id != config.AUTHORIZED_USER_ID:
            await event.respond("⛔ Unauthorized. This bot is for Marc's personal use only.")
            return
        return await func(event)
    return wrapper


@events.register(events.NewMessage(pattern='/start'))
@authorized_only
async def cmd_start(event):
    """Welcome message"""
    await event.respond(
        "👋 **Welcome to Mazkir!**\n\n"
        "Your Personal AI Assistant for productivity and motivation.\n\n"
        "**Quick commands:**\n"
        "/day - Today's note\n"
        "/tasks - Active tasks\n"
        "/habits - Habit tracker\n"
        "/tokens - Token balance\n"
        "/help - Full command list\n\n"
        "**Or just chat naturally:**\n"
        "• \"I completed gym\"\n"
        "• \"Show my streaks\"\n"
        "• \"Create task: buy milk\""
    )
    raise events.StopPropagation


@events.register(events.NewMessage(pattern='/day'))
@authorized_only
async def cmd_day(event):
    """Show today's daily note"""
    try:
        # Read today's daily note
        daily = vault.read_daily_note()
        metadata = daily['metadata']
        
        # Format response
        date = datetime.now(tz)
        day_name = metadata.get('day_of_week', date.strftime('%A'))
        
        response = f"📅 **{day_name}, {date.strftime('%B %d, %Y')}**\n\n"
        
        # Tokens
        tokens_today = metadata.get('tokens_earned', 0)
        tokens_total = metadata.get('tokens_total', 0)
        response += f"🪙 **Tokens Today:** {tokens_today}\n"
        response += f"💰 **Total Bank:** {tokens_total} tokens\n\n"
        
        # Habits
        response += "🎯 **Daily Habits**\n"
        completed_habits = metadata.get('completed_habits', [])
        
        # Get all active habits to show status
        active_habits = vault.list_active_habits()
        for habit_data in active_habits:
            habit_meta = habit_data['metadata']
            habit_name = habit_meta.get('name', 'Unknown')
            
            if habit_name in completed_habits:
                streak = habit_meta.get('streak', 0)
                response += f"✅ {habit_name} ({streak} day streak)\n"
            else:
                response += f"⏳ {habit_name}\n"
        
        response += "\n"
        
        # Tasks (from daily note content)
        # This is simplified - you might want to parse the markdown content
        response += "📋 **Tasks**\n"
        response += "_See /tasks for full list_\n\n"
        
        # Buttons
        buttons = [
            [Button.inline("✏️ Edit Note", b"edit_note")],
            [Button.inline("📊 Full Details", b"full_note")]
        ]
        
        await event.respond(response, buttons=buttons)
        
    except FileNotFoundError:
        await event.respond(
            "📝 No daily note for today yet.\n\n"
            "Would you like me to create one?",
            buttons=[
                [Button.inline("✅ Create Note", b"create_note")],
                [Button.inline("❌ Cancel", b"cancel")]
            ]
        )
    except Exception as e:
        await event.respond(f"❌ Error reading daily note: {str(e)}")
    
    raise events.StopPropagation


@events.register(events.NewMessage(pattern='/tasks'))
@authorized_only
async def cmd_tasks(event):
    """Show active tasks"""
    try:
        tasks = vault.list_active_tasks()
        
        if not tasks:
            await event.respond("✅ No active tasks! You're all caught up.")
            raise events.StopPropagation
        
        response = "📋 **Active Tasks**\n\n"
        
        # Group by priority
        high_priority = [t for t in tasks if t['metadata'].get('priority', 3) >= 4]
        medium_priority = [t for t in tasks if t['metadata'].get('priority', 3) == 3]
        low_priority = [t for t in tasks if t['metadata'].get('priority', 3) <= 2]
        
        today = datetime.now(tz).strftime('%Y-%m-%d')
        
        if high_priority:
            response += "🔴 **High Priority**\n"
            for task in high_priority:
                meta = task['metadata']
                name = meta.get('name', 'Unnamed task')
                due_date = meta.get('due_date')
                
                status = ""
                if due_date:
                    if due_date < today:
                        status = f" (overdue: {due_date})"
                    elif due_date == today:
                        status = " (due today)"
                
                response += f"• {name}{status}\n"
            response += "\n"
        
        if medium_priority:
            response += "🟡 **Medium Priority**\n"
            for task in medium_priority:
                meta = task['metadata']
                name = meta.get('name', 'Unnamed task')
                response += f"• {name}\n"
            response += "\n"
        
        if low_priority:
            response += "🟢 **Low Priority**\n"
            for task in low_priority:
                meta = task['metadata']
                name = meta.get('name', 'Unnamed task')
                response += f"• {name}\n"
            response += "\n"
        
        response += f"---\nTotal: {len(tasks)} active tasks"
        
        buttons = [
            [Button.inline("➕ Add Task", b"add_task")],
            [Button.inline("✅ Complete Task", b"complete_task")]
        ]
        
        await event.respond(response, buttons=buttons)
        
    except Exception as e:
        await event.respond(f"❌ Error loading tasks: {str(e)}")
    
    raise events.StopPropagation


@events.register(events.NewMessage(pattern='/habits'))
@authorized_only
async def cmd_habits(event):
    """Show habit tracker summary"""
    try:
        habits = vault.list_active_habits()
        
        if not habits:
            await event.respond("📝 No active habits yet. Create one to get started!")
            raise events.StopPropagation
        
        response = "💪 **Habit Tracker**\n\n"
        
        # Sort by streak (descending)
        habits.sort(key=lambda h: h['metadata'].get('streak', 0), reverse=True)
        
        today = datetime.now(tz).strftime('%Y-%m-%d')
        
        response += "🔥 **Active Streaks**\n"
        for habit in habits:
            meta = habit['metadata']
            name = meta.get('name', 'Unknown')
            streak = meta.get('streak', 0)
            last_completed = meta.get('last_completed')
            
            # Check if completed today
            completed_today = last_completed == today
            status = "✅" if completed_today else "⏳"
            
            response += f"{status} {name}: {streak} days"
            if completed_today:
                response += " (today)"
            response += "\n"
        
        response += "\n"
        
        # Stats
        total_streaks = sum(h['metadata'].get('streak', 0) for h in habits)
        avg_streak = total_streaks / len(habits) if habits else 0
        
        response += "📊 **Stats**\n"
        response += f"Total habits: {len(habits)}\n"
        response += f"Average streak: {avg_streak:.1f} days\n"
        
        buttons = [
            [Button.inline("✅ Log Habit", b"log_habit")],
            [Button.inline("📈 View Details", b"habit_details")]
        ]
        
        await event.respond(response, buttons=buttons)
        
    except Exception as e:
        await event.respond(f"❌ Error loading habits: {str(e)}")
    
    raise events.StopPropagation


@events.register(events.NewMessage(pattern='/tokens'))
@authorized_only
async def cmd_tokens(event):
    """Show token balance"""
    try:
        ledger = vault.read_token_ledger()
        metadata = ledger['metadata']
        
        total = metadata.get('total_tokens', 0)
        today = metadata.get('tokens_today', 0)
        all_time = metadata.get('all_time_tokens', 0)
        
        response = "🪙 **Motivation Tokens**\n\n"
        response += f"💰 **Current Balance:** {total} tokens\n"
        response += f"📈 **Today's Earnings:** +{today} tokens\n\n"
        
        # Try to get today's breakdown
        try:
            daily = vault.read_daily_note()
            # Parse content for token transactions
            # This is simplified - you might want better parsing
            response += "**Today's Activities:**\n"
            response += "_See daily note for details_\n\n"
        except:
            pass
        
        response += f"**All Time:** {all_time} tokens\n\n"
        
        # Next milestone
        next_milestone = ((total // 50) + 1) * 50
        tokens_needed = next_milestone - total
        response += f"🎯 **Next Milestone**\n"
        response += f"{next_milestone} tokens"
        if tokens_needed > 0:
            response += f" ({tokens_needed} tokens away!)"
        
        buttons = [
            [Button.inline("📊 Token History", b"token_history")],
            [Button.inline("🎁 Redeem", b"redeem_tokens")]
        ]
        
        await event.respond(response, buttons=buttons)
        
    except Exception as e:
        await event.respond(f"❌ Error loading tokens: {str(e)}")
    
    raise events.StopPropagation


@events.register(events.NewMessage(pattern='/help'))
@authorized_only
async def cmd_help(event):
    """Show help message"""
    await event.respond(
        "📖 **Mazkir Bot Commands**\n\n"
        "**Quick Access**\n"
        "/day - Today's daily note\n"
        "/tasks - Your active tasks\n"
        "/habits - Habit tracker\n"
        "/tokens - Token balance\n\n"
        "**Natural Language**\n"
        "Just chat naturally! Examples:\n"
        "• \"I completed gym\"\n"
        "• \"Show my streaks\"\n"
        "• \"Create task: buy milk\"\n"
        "• \"What's my progress on learning ML?\"\n\n"
        "**Settings**\n"
        "/settings - Configure notifications\n\n"
        "Need help? Just ask!"
    )
    raise events.StopPropagation


# Natural language handler (catch-all)
@events.register(events.NewMessage())
@authorized_only
async def handle_message(event):
    """Handle natural language messages via Claude"""
    # Skip if it's a command
    if event.message.text.startswith('/'):
        return
    
    try:
        # Show typing indicator
        async with event.client.action(event.chat_id, 'typing'):
            # Get Claude's response
            response = claude.chat(event.message.text)
            
            # Send response
            await event.respond(response)
    
    except Exception as e:
        await event.respond(f"❌ Sorry, I encountered an error: {str(e)}")
    
    raise events.StopPropagation


# Export handlers
def get_handlers():
    """Return list of event handlers"""
    return [
        cmd_start,
        cmd_day,
        cmd_tasks,
        cmd_habits,
        cmd_tokens,
        cmd_help,
        handle_message  # Must be last (catch-all)
    ]
```

### Step 6: Update Main Entry Point

**File:** `src/main.py`

```python
import asyncio
import logging
from telethon import TelegramClient
from src.config import config
from src.bot.handlers import get_handlers

# Configure logging
logging.basicConfig(
    level=logging.INFO if config.DEBUG else logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main():
    """Main bot entry point"""
    
    # Validate configuration
    try:
        config.validate()
    except AssertionError as e:
        logger.error(f"Configuration error: {e}")
        return
    
    logger.info("Starting Mazkir bot...")
    
    # Create Telegram client
    client = TelegramClient(
        'mazkir_session',
        config.TELEGRAM_API_ID,
        config.TELEGRAM_API_HASH
    )
    
    # Register handlers
    for handler in get_handlers():
        client.add_event_handler(handler)
    
    logger.info("Handlers registered")
    
    # Start client
    await client.start(phone=config.TELEGRAM_PHONE)
    
    logger.info("Bot started successfully!")
    logger.info(f"Vault: {config.VAULT_PATH}")
    logger.info(f"Authorized user: {config.AUTHORIZED_USER_ID}")
    
    # Run until disconnected
    await client.run_until_disconnected()


if __name__ == '__main__':
    asyncio.run(main())
```

---

## Testing Checklist

### Phase 1: Basic Setup

- [ ] Dependencies installed
- [ ] `.env` configured with all keys
- [ ] Vault path correct and accessible
- [ ] AGENTS.md present in vault
- [ ] Bot starts without errors

### Phase 2: Vault Service

- [ ] Can read daily note
- [ ] Can read habit files
- [ ] Can read task files
- [ ] Can update files
- [ ] Frontmatter preserved correctly

### Phase 3: Commands

- [ ] `/start` shows welcome message
- [ ] `/day` shows today's note
- [ ] `/tasks` lists active tasks
- [ ] `/habits` shows habit tracker
- [ ] `/tokens` displays balance
- [ ] `/help` shows command list

### Phase 4: Natural Language

- [ ] "I completed gym" updates habit
- [ ] Tokens are awarded
- [ ] Daily note updated
- [ ] Response is encouraging

---

## Next Steps

After Phase 1 is complete:

1. **Test extensively** with real vault data
2. **Refine Claude prompts** for better responses
3. **Add error handling** for edge cases
4. **Implement button callbacks** (inline buttons)
5. **Add notifications** (daily reminders)
6. **Phase 2: Advanced features**
   - Task creation via chat
   - Goal progress queries
   - Weekly review generation
7. **Phase 3: WebApp**
   - Daily note renderer
   - Habit calendar view
   - Token history chart

---

## Common Issues & Solutions

### Issue: Bot not responding
- Check AUTHORIZED_USER_ID matches your Telegram user ID
- Verify bot is running (check logs)
- Ensure Telegram session is active

### Issue: File not found errors
- Verify VAULT_PATH is correct
- Check file exists in vault
- Ensure proper permissions

### Issue: Frontmatter errors
- Validate YAML syntax in files
- Check required fields present
- Use python-frontmatter library correctly

### Issue: Claude API errors
- Verify API key is valid
- Check rate limits
- Review error messages in logs

---

## Deployment Notes

### systemd Service

Create `/etc/systemd/system/tg-mazkir.service`:

```ini
[Unit]
Description=Mazkir Telegram Bot
After=network.target postgresql.service

[Service]
Type=simple
User=marcellmc
WorkingDirectory=/path/to/tg-mazkir
Environment="PATH=/path/to/tg-mazkir/venv/bin"
ExecStart=/path/to/tg-mazkir/venv/bin/python -m src.main
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable tg-mazkir
sudo systemctl start tg-mazkir
sudo systemctl status tg-mazkir
```

---

**End of Phase 1 Implementation Guide**

Continue to WEBAPP.md for Phase 3 specifications.
