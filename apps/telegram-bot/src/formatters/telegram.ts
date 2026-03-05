import type {
  DailyResponse,
  Task,
  Habit,
  Goal,
  TokensResponse,
  CalendarEvent,
  MessageResponse,
} from "@mazkir/shared-types";

export function progressBar(percent: number, length = 10): string {
  const filled = Math.round((percent / 100) * length);
  return "█".repeat(filled) + "░".repeat(length - filled);
}

export function formatTime(isoString: string): string {
  if (!isoString.includes("T")) return "All day";
  const date = new Date(isoString);
  return date.toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function priorityEmoji(priority: number): string {
  if (priority >= 4) return "🔴";
  if (priority === 3) return "🟡";
  return "🟢";
}

export function formatDay(data: DailyResponse): string {
  const lines: string[] = [];
  lines.push(`📅 <b>Daily Note — ${data.date}</b>`);
  lines.push(`🪙 Tokens today: <b>${data.tokens_earned}</b> | Total: <b>${data.tokens_total}</b>`);
  lines.push("");

  if (data.habits.length > 0) {
    lines.push("💪 <b>Habits</b>");
    for (const h of data.habits) {
      const icon = h.completed ? "✅" : "⏳";
      lines.push(`  ${icon} ${h.name} — 🔥 ${h.streak} day streak`);
    }
    lines.push("");
  }

  if (data.calendar_events.length > 0) {
    lines.push("📆 <b>Schedule</b>");
    for (const e of data.calendar_events) {
      const time = formatTime(e.start);
      const icon = e.completed ? "✅" : "⏳";
      const summary = e.summary.replace(/^✅\s*/, "");
      const cal = e.calendar !== "Mazkir" ? ` (${e.calendar})` : "";
      lines.push(`  ${icon} ${time} — ${summary}${cal}`);
    }
  }

  if (data.notes && data.notes.length > 0) {
    lines.push("");
    lines.push("📝 <b>Notes</b>");
    for (const note of data.notes) {
      // Strip markdown image syntax, show caption text only
      const cleaned = note
        .replace(/!\[([^\]]*)\]\([^)]*\)/g, "📷 $1") // ![caption](path) → 📷 caption
        .replace(/\[\[([^\]]*)\]\]/g, "$1"); // [[wikilink]] → wikilink
      lines.push(`  ${cleaned}`);
    }
  }

  return lines.join("\n");
}

export function formatTasks(tasks: Task[]): string {
  if (tasks.length === 0) return "📋 No active tasks. Enjoy the calm!";

  const lines: string[] = ["📋 <b>Active Tasks</b>\n"];

  const high = tasks.filter((t) => t.priority >= 4);
  const medium = tasks.filter((t) => t.priority === 3);
  const low = tasks.filter((t) => t.priority <= 2);

  if (high.length > 0) {
    lines.push("🔴 <b>High Priority</b>");
    for (const t of high) lines.push(`  ⏳ ${t.name}${t.due_date ? ` (due ${t.due_date})` : ""}`);
    lines.push("");
  }
  if (medium.length > 0) {
    lines.push("🟡 <b>Medium Priority</b>");
    for (const t of medium) lines.push(`  ⏳ ${t.name}${t.due_date ? ` (due ${t.due_date})` : ""}`);
    lines.push("");
  }
  if (low.length > 0) {
    lines.push("🟢 <b>Low Priority</b>");
    for (const t of low) lines.push(`  ⏳ ${t.name}${t.due_date ? ` (due ${t.due_date})` : ""}`);
  }

  return lines.join("\n");
}

export function formatHabits(habits: Habit[]): string {
  if (habits.length === 0) return "💪 No habits tracked yet.";

  const lines: string[] = ["💪 <b>Habit Tracker</b>\n"];
  for (const h of habits) {
    const icon = h.completed_today ? "✅" : "⏳";
    lines.push(`${icon} <b>${h.name}</b> — 🔥 ${h.streak} day streak`);
  }

  const avgStreak =
    habits.length > 0
      ? Math.round(habits.reduce((s, h) => s + h.streak, 0) / habits.length)
      : 0;
  lines.push(`\n📊 Average streak: <b>${avgStreak} days</b>`);

  return lines.join("\n");
}

export function formatGoals(goals: Goal[]): string {
  if (goals.length === 0) return "🎯 No active goals.";

  const lines: string[] = ["🎯 <b>Goals</b>\n"];
  for (const g of goals) {
    const emoji = priorityEmoji(g.priority);
    const bar = progressBar(g.progress);
    lines.push(`${emoji} <b>${g.name}</b>`);
    lines.push(`   ${bar} ${g.progress}%`);
    if (g.target_date) lines.push(`   📅 Target: ${g.target_date}`);
    lines.push("");
  }

  return lines.join("\n");
}

export function formatTokens(data: TokensResponse): string {
  const lines: string[] = [];
  lines.push("🪙 <b>Motivation Tokens</b>\n");
  lines.push(`💰 Balance: <b>${data.total}</b>`);
  lines.push(`📈 Today: <b>+${data.today}</b>`);
  lines.push(`🏆 All-time: <b>${data.all_time}</b>`);

  // Next milestone
  const milestones = [50, 100, 250, 500, 1000, 2500, 5000];
  const next = milestones.find((m) => m > data.total);
  if (next) {
    lines.push(`\n🎯 Next milestone: <b>${next}</b> (${next - data.total} to go)`);
  }

  return lines.join("\n");
}

export function formatCalendar(events: CalendarEvent[]): string {
  if (events.length === 0) return "📆 No events scheduled today.";

  const lines: string[] = ["📆 <b>Today's Schedule</b>\n"];
  for (const e of events) {
    const time = formatTime(e.start);
    const icon = e.completed ? "✅" : "⏳";
    const summary = e.summary.replace(/^✅\s*/, "");
    const cal = e.calendar !== "Mazkir" ? ` (${e.calendar})` : "";
    lines.push(`${icon} <b>${time}</b> — ${summary}${cal}`);
  }

  return lines.join("\n");
}

export function formatNlResponse(data: MessageResponse): string {
  return data.response;
}
