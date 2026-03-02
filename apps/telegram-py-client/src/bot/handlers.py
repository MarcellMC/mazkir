"""Message and command handlers for the bot (thin client)."""
import logging
from telethon import events
from dateutil import parser as dateutil_parser
from src.config import settings
from src.api_client import VaultAPIClient

logger = logging.getLogger(__name__)

# API client (initialized on import)
api = VaultAPIClient(
    base_url=settings.vault_server_url,
    api_key=settings.vault_server_api_key,
)

# Pending confirmations: chat_id → pending_action_id
_pending_confirmations: dict[int, str] = {}


# Middleware: Only allow authorized user
def authorized_only(func):
    async def wrapper(event):
        if event.sender_id != settings.authorized_user_id:
            await event.respond("⛔ Unauthorized. This bot is for Marc's personal use only.")
            return
        return await func(event)
    return wrapper


@authorized_only
async def cmd_start(event):
    await event.respond(
        "👋 **Welcome to Mazkir!**\n\n"
        "Your Personal AI Assistant for productivity and motivation.\n\n"
        "**Quick commands:**\n"
        "/day - Today's note\n"
        "/tasks - Active tasks\n"
        "/habits - Habit tracker\n"
        "/goals - Active goals\n"
        "/tokens - Token balance\n"
        "/help - Full command list\n\n"
        "**Or just chat naturally:**\n"
        '• "I completed gym" - Log a habit\n'
        '• "Create task: buy milk" - Add a task\n'
        '• "Create goal: learn python" - Set a goal\n'
        '• "Done with groceries" - Complete a task'
    )
    raise events.StopPropagation


@authorized_only
async def cmd_day(event):
    try:
        data = await api.get_daily()

        day = data.get("day_of_week", "")
        date = data.get("date", "")
        response = f"📅 **{day}, {date}**\n\n"

        response += f"🪙 **Tokens Today:** {data.get('tokens_earned', 0)}\n"
        response += f"💰 **Total Bank:** {data.get('tokens_total', 0)} tokens\n\n"

        response += "🎯 **Daily Habits**\n"
        for h in data.get("habits", []):
            if h["completed"]:
                streak_info = f" ({h['streak']} day streak)"
                response += f"✅ {h['name']}{streak_info}\n"
            else:
                response += f"⏳ {h['name']}\n"
        response += "\n"

        response += "📋 **Tasks**\n__See /tasks for full list__\n\n"

        events_list = data.get("calendar_events", [])
        if events_list:
            response += "📆 **Today's Schedule**\n"
            for evt in events_list:
                start_str = evt.get("start", "")
                if "T" in start_str:
                    start_time = dateutil_parser.parse(start_str)
                    time_fmt = start_time.strftime("%H:%M")
                else:
                    time_fmt = "All day"
                status = "✅" if evt.get("completed") else "⏳"
                summary = evt.get("summary", "Event")
                if summary.startswith("✅ "):
                    summary = summary[2:]
                cal_name = evt.get("calendar", "")
                if cal_name and cal_name != "Mazkir":
                    response += f"{status} {time_fmt} - {summary} __({cal_name})__\n"
                else:
                    response += f"{status} {time_fmt} - {summary}\n"

        await event.respond(response)
    except Exception as e:
        await event.respond(f"❌ Error reading daily note: {str(e)}")

    raise events.StopPropagation


@authorized_only
async def cmd_tasks(event):
    try:
        tasks = await api.list_tasks()

        if not tasks:
            await event.respond("✅ No active tasks! You're all caught up.")
            raise events.StopPropagation

        response = "📋 **Active Tasks**\n\n"

        high = [t for t in tasks if t.get("priority", 3) >= 4]
        medium = [t for t in tasks if t.get("priority", 3) == 3]
        low = [t for t in tasks if t.get("priority", 3) <= 2]

        if high:
            response += "🔴 **High Priority**\n"
            for t in high:
                response += f"• {t['name']}\n"
            response += "\n"
        if medium:
            response += "🟡 **Medium Priority**\n"
            for t in medium:
                response += f"• {t['name']}\n"
            response += "\n"
        if low:
            response += "🟢 **Low Priority**\n"
            for t in low:
                response += f"• {t['name']}\n"
            response += "\n"

        response += f"---\nTotal: {len(tasks)} active tasks"
        await event.respond(response)
    except Exception as e:
        await event.respond(f"❌ Error loading tasks: {str(e)}")

    raise events.StopPropagation


@authorized_only
async def cmd_habits(event):
    try:
        habits = await api.list_habits()

        if not habits:
            await event.respond("📝 No active habits yet. Create one to get started!")
            raise events.StopPropagation

        response = "💪 **Habit Tracker**\n\n🔥 **Active Streaks**\n"

        for h in habits:
            status = "✅" if h.get("completed_today") else "⏳"
            response += f"{status} {h['name']}: {h['streak']} days"
            if h.get("completed_today"):
                response += " (today)"
            response += "\n"
        response += "\n"

        total_streaks = sum(h.get("streak", 0) for h in habits)
        avg = total_streaks / len(habits) if habits else 0
        response += f"📊 **Stats**\nTotal habits: {len(habits)}\nAverage streak: {avg:.1f} days"

        await event.respond(response)
    except Exception as e:
        await event.respond(f"❌ Error loading habits: {str(e)}")

    raise events.StopPropagation


@authorized_only
async def cmd_goals(event):
    try:
        goals = await api.list_goals()

        if not goals:
            await event.respond("🎯 No active goals! Use /help to see how to create goals.")
            raise events.StopPropagation

        response = "🎯 **Active Goals**\n\n"

        for g in goals:
            priority = g.get("priority", "medium")
            progress = g.get("progress", 0)
            progress_bars = int(progress / 10)
            progress_bar = "█" * progress_bars + "░" * (10 - progress_bars)

            priority_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(
                str(priority).lower(), "🟡"
            )

            response += f"{priority_emoji} **{g['name']}**\n"
            response += f"Status: {g.get('status', 'unknown')}\n"
            response += f"📊 Progress: [{progress_bar}] {progress}%\n"

            target = g.get("target_date")
            if target:
                response += f"📅 Target: {target}\n"
            response += "\n"

        response += f"---\nTotal: {len(goals)} active goals"
        await event.respond(response)
    except Exception as e:
        await event.respond(f"❌ Error loading goals: {str(e)}")

    raise events.StopPropagation


@authorized_only
async def cmd_tokens(event):
    try:
        data = await api.get_tokens()

        response = "🪙 **Motivation Tokens**\n\n"
        response += f"💰 **Current Balance:** {data['total']} tokens\n"
        response += f"📈 **Today's Earnings:** +{data['today']} tokens\n"
        response += f"⭐ **All Time:** {data['all_time']} tokens\n\n"

        next_milestone = ((data["total"] // 50) + 1) * 50
        needed = next_milestone - data["total"]
        response += f"🎯 **Next Milestone:** {next_milestone} tokens"
        if needed > 0:
            response += f" ({needed} tokens away!)"

        await event.respond(response)
    except Exception as e:
        await event.respond(f"❌ Error loading tokens: {str(e)}")

    raise events.StopPropagation


@authorized_only
async def cmd_calendar(event):
    try:
        events_list = await api.get_calendar_events()

        if not events_list:
            await event.respond("📆 **Today's Schedule**\n\nNo events scheduled for today.")
            raise events.StopPropagation

        response = "📆 **Today's Schedule**\n\n"
        for evt in events_list:
            start_str = evt.get("start", "")
            if "T" in start_str:
                start_time = dateutil_parser.parse(start_str)
                time_fmt = start_time.strftime("%H:%M")
            else:
                time_fmt = "All day"
            status = "✅" if evt.get("completed") else "⏳"
            summary = evt.get("summary", "Event")
            if summary.startswith("✅ "):
                summary = summary[2:]
            cal_name = evt.get("calendar", "")
            if cal_name and cal_name != "Mazkir":
                response += f"{status} **{time_fmt}** - {summary} __({cal_name})__\n"
            else:
                response += f"{status} **{time_fmt}** - {summary}\n"

        completed = sum(1 for e in events_list if e.get("completed"))
        response += f"\n---\nCompleted: {completed}/{len(events_list)}"

        await event.respond(response)
    except Exception as e:
        if "503" in str(e):
            await event.respond("📆 **Calendar not enabled**\n\nCalendar sync is disabled on the server.")
        else:
            await event.respond(f"❌ Error loading calendar: {str(e)}")

    raise events.StopPropagation


@authorized_only
async def cmd_sync_calendar(event):
    try:
        await event.respond("🔄 Syncing to Google Calendar...")
        result = await api.sync_calendar()

        response = "✅ **Calendar Sync Complete**\n\n"
        response += f"📅 Habits synced: {result['habits_synced']}\n"
        response += f"📋 Tasks synced: {result['tasks_synced']}\n"
        if result.get("errors", 0) > 0:
            response += f"⚠️ Errors: {result['errors']}\n"

        await event.respond(response)
    except Exception as e:
        if "503" in str(e):
            await event.respond("📆 **Calendar not enabled**\n\nCalendar sync is disabled on the server.")
        else:
            await event.respond(f"❌ Error syncing calendar: {str(e)}")

    raise events.StopPropagation


@authorized_only
async def cmd_help(event):
    await event.respond(
        "📖 **Mazkir Bot Commands**\n\n"
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
        "__Complete activities:__\n"
        '• "I completed gym"\n'
        '• "Done with buy groceries"\n\n'
        "__Create items:__\n"
        '• "Create task: buy milk"\n'
        '• "Create habit: morning run"\n'
        '• "Create goal: learn python"\n\n'
        "__Ask questions:__\n"
        '• "Show my streaks"\n'
        '• "What are my tokens?"\n\n'
        "Need help? Just ask!"
    )
    raise events.StopPropagation


@authorized_only
async def handle_message(event):
    """Handle natural language messages through the agent loop."""
    if event.message.text.startswith("/"):
        return

    try:
        async with event.client.action(event.chat_id, "typing"):
            chat_id = event.chat_id

            if chat_id in _pending_confirmations:
                action_id = _pending_confirmations.pop(chat_id)
                result = await api.send_confirmation(
                    chat_id=chat_id,
                    action_id=action_id,
                    response=event.message.text,
                )
            else:
                result = await api.send_message(event.message.text, chat_id)

            if result.get("awaiting_confirmation"):
                _pending_confirmations[chat_id] = result["pending_action_id"]

            await event.respond(result.get("response", "No response received."))
    except Exception as e:
        logger.error(f"Error in NL handler: {e}", exc_info=True)
        await event.respond(f"Sorry, I encountered an error: {str(e)}")

    raise events.StopPropagation


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
