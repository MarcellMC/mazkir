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

        response += "📋 **Tasks**\n_See /tasks for full list_\n\n"

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
                    response += f"{status} {time_fmt} - {summary} _({cal_name})_\n"
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
                response += f"{status} **{time_fmt}** - {summary} _({cal_name})_\n"
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
        "_Complete activities:_\n"
        '• "I completed gym"\n'
        '• "Done with buy groceries"\n\n'
        "_Create items:_\n"
        '• "Create task: buy milk"\n'
        '• "Create habit: morning run"\n'
        '• "Create goal: learn python"\n\n'
        "_Ask questions:_\n"
        '• "Show my streaks"\n'
        '• "What are my tokens?"\n\n'
        "Need help? Just ask!"
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
        await event.respond(f"❌ Sorry, I encountered an error: {str(e)}")

    raise events.StopPropagation


def _format_nl_response(intent: str, data: dict) -> str:
    """Format vault-server NL response for Telegram display."""
    if data.get("error"):
        available = data.get("available", [])
        msg = f"❌ {data['error']}"
        if available:
            msg += f"\n\nAvailable: {', '.join(str(a) for a in available)}"
        return msg

    if intent == "HABIT_COMPLETION":
        if data.get("already_completed"):
            return f"✅ You already completed **{data['name']}** today! Streak: {data['streak']} days"
        response = f"💪 Excellent! **{data['name']}** completed!\n\n"
        response += f"🔥 Streak: {data['old_streak']} → **{data['new_streak']} days**\n"
        response += f"🪙 Tokens: +{data['tokens_earned']}\n"
        response += f"💰 New balance: **{data['new_token_total']} tokens**"
        streak = data["new_streak"]
        if streak == 7:
            response += "\n\n🎉 One week streak! Keep it up!"
        elif streak == 30:
            response += "\n\n🏆 30 days! You're building a solid habit!"
        elif streak == 100:
            response += "\n\n⭐ 100 days! Legendary!"
        elif streak % 10 == 0:
            response += f"\n\n✨ {streak} days! You're on fire!"
        return response

    elif intent == "HABIT_CREATION":
        response = f"✅ Habit created: **{data['name']}**\n"
        response += f"📅 Frequency: {data.get('frequency', 'daily')}\n\n"
        response += "Use /habits to view your tracker."
        return response

    elif intent == "TASK_CREATION":
        priority_label = {5: "🔴 High", 4: "🔴 High", 3: "🟡 Medium", 2: "🟢 Low", 1: "🟢 Low"}.get(data.get("priority", 3), "🟡 Medium")
        response = f"✅ Task created: **{data['name']}**\nPriority: {priority_label}\n"
        if data.get("due_date"):
            response += f"📅 Due: {data['due_date']}\n"
        response += "\nUse /tasks to view all active tasks."
        return response

    elif intent == "TASK_COMPLETION":
        response = f"✅ Task completed: **{data['task_name']}**\n"
        if data.get("tokens_earned", 0) > 0:
            response += f"🪙 Tokens earned: +{data['tokens_earned']}\n"
        response += "\nGreat job! Use /tasks to see remaining tasks."
        return response

    elif intent == "GOAL_CREATION":
        priority = data.get("priority", "medium")
        priority_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(str(priority).lower(), "🟡")
        response = f"🎯 Goal created: **{data['name']}**\n"
        response += f"{priority_emoji} Priority: {data.get('priority', 'medium')}\n"
        response += "\nUse /goals to view your active goals."
        return response

    elif intent == "QUERY":
        if data.get("query_type") == "streaks":
            lines = ["🔥 **Your Habit Streaks**\n"]
            for h in data.get("data", []):
                lines.append(f"• **{h['name']}**: {h['streak']} days (best: {h['longest']})")
            return "\n".join(lines)
        elif data.get("query_type") == "tokens":
            d = data.get("data", {})
            return f"🪙 **Token Balance**\n\n💰 Current: **{d.get('total', 0)} tokens**\n📈 Today: +{d.get('today', 0)}\n⭐ All time: {d.get('all_time', 0)}"
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
