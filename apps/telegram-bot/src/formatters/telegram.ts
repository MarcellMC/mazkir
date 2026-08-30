import type {
  Task,
  TaskDetail,
  Habit,
  Goal,
  GoalDetail,
  GoalPriority,
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

/** Goals store priority as "high" | "medium" | "low"; map those onto the
 * numeric scale before picking an emoji. */
function goalPriorityEmoji(priority: GoalPriority): string {
  if (typeof priority === "number") return priorityEmoji(priority);
  const scale: Record<string, number> = { high: 5, medium: 3, low: 1 };
  return priorityEmoji(scale[priority.toLowerCase()] ?? 3);
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
export function stripEmptySections(content: string): string {
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
  goals.forEach((g, i) => {
    const emoji = goalPriorityEmoji(g.priority);
    const bar = progressBar(g.progress);
    lines.push(`${emoji} <b>${i + 1}. ${escapeHtml(g.name)}</b>`);
    lines.push(`   ${bar} ${g.progress}%`);
    if (g.target_date) lines.push(`   📅 Target: ${escapeHtml(g.target_date)}`);
    lines.push("");
  });

  return lines.join("\n");
}

export function formatGoalDetail(goal: GoalDetail): string {
  const lines: string[] = [`🎯 <b>${escapeHtml(goal.name)}</b>\n`];

  lines.push(`${progressBar(goal.progress)} ${goal.progress}%`);
  lines.push(`${goalPriorityEmoji(goal.priority)} Priority: <b>${escapeHtml(String(goal.priority))}</b>`);
  lines.push(`📌 Status: ${escapeHtml(goal.status)}`);
  if (goal.category) lines.push(`🏷 Category: ${escapeHtml(goal.category)}`);
  if (goal.start_date) lines.push(`🕐 Started: ${escapeHtml(String(goal.start_date))}`);
  if (goal.target_date) lines.push(`📅 Target: ${escapeHtml(String(goal.target_date))}`);

  // Milestone entries are free-form in the vault; render the plain-string
  // ones and leave anything richer to the note body below.
  const milestones = (goal.milestones ?? []).filter((m) => typeof m === "string");
  if (milestones.length > 0) {
    lines.push("", "🚩 <b>Milestones</b>");
    for (const m of milestones) lines.push(`  • ${escapeHtml(m)}`);
  }

  const body = stripEmptySections(goal.content);
  if (body) {
    const truncated =
      body.length > DETAIL_BODY_MAX ? body.slice(0, DETAIL_BODY_MAX) + "…" : body;
    lines.push("", `<blockquote>${escapeHtml(truncated)}</blockquote>`);
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
