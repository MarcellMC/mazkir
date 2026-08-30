import type {
  TokensResponse,
  CalendarEvent,
  MessageResponse,
} from "@mazkir/shared-types";

/** What is left here after the list views became rich messages: the shared
 *  helpers every formatter needs (escapeHtml, progressBar,
 *  stripEmptySections, formatTime) plus the views that are still classic
 *  HTML `parse_mode` messages — /calendar, /tokens, and the agent's NL reply.
 *
 *  The task, habit and goal formatters moved to tasks-rich.ts,
 *  habits-rich.ts and goals-rich.ts. They had to: their in-view buttons now
 *  render in the message body as `<tg-button-row>` elements, which only a
 *  rich message can carry. */

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

/** Drop the "# Title" heading and `## Section` blocks with no real content
 * (template boilerplate like an empty Description or a lone `- [ ]`).
 * Shared by the task and goal detail views in tasks-rich.ts / goals-rich.ts. */
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
