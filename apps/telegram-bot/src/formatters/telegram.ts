import type {
  DailyResponse,
  Task,
  TaskDetail,
  Habit,
  Goal,
  TokensResponse,
  CalendarEvent,
  MessageResponse,
} from "@mazkir/shared-types";


export function escapeHtml(text: string): string {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

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
  lines.push(`🪙 Tokens today: <b>${data.tokens_today}</b> | Total: <b>${data.tokens_total}</b>`);
  lines.push("");

  if (data.schedule.length > 0) {
    lines.push("📆 <b>Schedule</b>");
    for (const item of data.schedule) {
      const icon = item.completed ? "✅" : item.source === "habit" ? "🔁" : "⏳";
      const time = item.start.includes("T") ? formatTime(item.start) : item.start;
      const cal = item.calendar_name && item.calendar_name !== "Mazkir" ? ` (${item.calendar_name})` : "";
      lines.push(`  ${icon} ${time} — ${item.title}${cal}`);
    }
  }

  if (data.notes && data.notes.length > 0) {
    if (data.schedule.length > 0) lines.push("");
    lines.push("📝 <b>Notes</b>");
    for (const n of data.notes) {
      const text = n.text ?? (n.caption ? `📷 ${n.caption}` : "📷");
      lines.push(`  ${text}`);
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

  let n = 1;
  if (high.length > 0) {
    lines.push("🔴 <b>High Priority</b>");
    for (const t of high) lines.push(`  ${n++}. ⏳ ${t.name}${t.due_date ? ` (due ${t.due_date})` : ""}`);
    lines.push("");
  }
  if (medium.length > 0) {
    lines.push("🟡 <b>Medium Priority</b>");
    for (const t of medium) lines.push(`  ${n++}. ⏳ ${t.name}${t.due_date ? ` (due ${t.due_date})` : ""}`);
    lines.push("");
  }
  if (low.length > 0) {
    lines.push("🟢 <b>Low Priority</b>");
    for (const t of low) lines.push(`  ${n++}. ⏳ ${t.name}${t.due_date ? ` (due ${t.due_date})` : ""}`);
  }

  return lines.join("\n");
}

const PRIORITY_ICONS: Record<number, string> = { 5: "🔴", 4: "🔴", 3: "🟡", 2: "🟢", 1: "🟢" };
const DETAIL_BODY_MAX = 800;

/** Drop the "# Title" heading and `## Section` blocks with no real content
 * (template boilerplate like an empty Description or a lone `- [ ]`). */
function stripEmptySections(content: string): string {
  const withoutTitle = content.replace(/^#\s+.*\n?/, "");
  const blocks = withoutTitle.split(/^(?=##\s)/m);
  const kept = blocks.filter((block) => {
    if (!block.startsWith("## ")) return block.trim().length > 0;
    const body = block.split("\n").slice(1).join("\n");
    return body.replaceAll(/- \[ \]\s*$/gm, "").trim().length > 0;
  });
  return kept.join("").trim();
}

export function formatTaskDetail(task: TaskDetail): string {
  const lines: string[] = [`📋 <b>${escapeHtml(task.name)}</b>\n`];

  const icon = PRIORITY_ICONS[task.priority] ?? "🟡";
  lines.push(`${icon} Priority: <b>${task.priority}</b>`);
  if (task.category) lines.push(`🏷 Category: ${escapeHtml(task.category)}`);
  if (task.due_date) lines.push(`📅 Due: ${escapeHtml(String(task.due_date))}`);
  lines.push(`📌 Status: ${escapeHtml(task.status)}`);
  if (task.tokens_on_completion != null) {
    lines.push(`🪙 Tokens on completion: ${task.tokens_on_completion}`);
  }
  if (task.created) lines.push(`🕐 Created: ${escapeHtml(String(task.created))}`);
  if (task.google_event_id) lines.push(`📆 Synced to Google Calendar`);

  // Note body: drop the title heading (duplicates the name) and empty
  // template sections, keep everything the user actually wrote.
  const body = stripEmptySections(task.content);
  if (body) {
    const truncated =
      body.length > DETAIL_BODY_MAX ? body.slice(0, DETAIL_BODY_MAX) + "…" : body;
    lines.push("", `<blockquote>${escapeHtml(truncated)}</blockquote>`);
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
