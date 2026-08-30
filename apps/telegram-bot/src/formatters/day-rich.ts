import type { InputFile } from "grammy";
import type { InputRichMessage } from "@grammyjs/types";
import type { DailyResponse, DailyBlock, DailyGap } from "@mazkir/shared-types";
import { config } from "../config.js";
import { escapeHtml } from "./telegram.js";

/** Rich messages are authored as HTML here rather than markdown because
 *  button syntax (`<tg-button>`) has no markdown equivalent. That also means
 *  escapeHtml remains the right tool for user text — a miss renders wrong
 *  rather than losing the whole message, which is what HTML parse_mode did. */

// Sunday-first, matching the Hebrew week. Index 0 == Sunday (getUTCDay()'s
// own numbering) through index 6 == Saturday.
const WEEKDAY_PREFIXES = ["א", "ב", "ג", "ד", "ה", "ו", "✨ש"];

function hours(minutes: number): string {
  return `${(minutes / 60).toFixed(1)}h`;
}

function shiftDate(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

function headerLabel(iso: string, today: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  const label = d.toLocaleDateString("en-GB", {
    weekday: "short", day: "numeric", month: "short", timeZone: "UTC",
  });
  return iso === today ? `${label} · today` : label;
}

function facetLabel(b: DailyBlock): string {
  // Render whichever facets exist: a block can have an activity without a
  // category (or vice versa) — Ship 6 populates them independently, and
  // discarding a partial classification throws away the only signal a
  // block has.
  if (b.activity && b.category) return `${escapeHtml(b.activity)} × ${escapeHtml(b.category)}`;
  if (b.activity) return escapeHtml(b.activity);
  if (b.category) return escapeHtml(b.category);
  return "";
}

function blockRow(b: DailyBlock, ahead: boolean): string {
  // Completion is prefixed to the TIME column, not put in the marker
  // column: `habit_progress` and the facet label already live there, and a
  // completed habit has both. Prefixing also puts it in the same column as
  // the gap row's `⚠`, so the leftmost cell reads as one status channel
  // down the timeline. Ship 1 rendered `✅ 14:00 — Standup`; this restores
  // that for every source, not just habits.
  //
  // `⟳` (still ahead) shares the same prefix slot: a block cannot be both
  // completed and still ahead of "now", so the two never collide, and the
  // third column stays free for `habit_progress`/facet classification.
  const prefix = b.completed ? "✅ " : ahead ? "⟳ " : "";
  const marker = b.habit_progress ? escapeHtml(b.habit_progress) : facetLabel(b);
  return `<tr><td>${prefix}${b.start}–${b.end}</td><td>${escapeHtml(b.title)}</td><td>${marker}</td></tr>`;
}

function gapRow(g: DailyGap): string {
  return `<tr><td>⚠ ${g.start}–${g.end}</td><td>—</td><td>${hours(g.minutes)}</td></tr>`;
}

const MINUTES_PER_DAY = 24 * 60;

/** "HH:MM" -> minutes since midnight. Deliberately not a `Date` parse — the
 *  spec is explicit that block/gap `start` values are wall-clock offsets,
 *  not calendar timestamps, and parsing them as dates would drag in a
 *  timezone this arithmetic has no business knowing about. */
function toMinutes(hhmm: string): number {
  const [h, m] = hhmm.split(":").map(Number);
  return (h ?? 0) * 60 + (m ?? 0);
}

/** Sunday of the week containing `iso`, computed with the same UTC-safe
 *  arithmetic as `shiftDate` (parse with an explicit `Z`, only
 *  `setUTCDate`/`getUTCDay`/`toISOString` — never a local-time getter, which
 *  would shift the result across a DST boundary). `getUTCDay()` already
 *  returns 0 for Sunday, so shifting back by that many days lands on it. */
function weekStart(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  return shiftDate(iso, -d.getUTCDay());
}

/** Fixed Sunday->Saturday week, so a given weekday always sits in the same
 *  column and the arrows page a week at a time rather than sliding the
 *  centre day around. Button labels are plain text only — Bot API 10.3
 *  buttons accept "only plain text, RichTextCustomEmoji and
 *  RichTextDateTime entities" (@grammyjs/types 5.0.0), so there is no bold,
 *  superscript, or font-size markup available to mark Saturday gold. Do NOT
 *  attempt <sub>, superscript, or size markup inside a button label here —
 *  it will not render; the ✨ emoji prefix is the deliberate substitute. */
function weekBar(selected: string): string {
  const sunday = weekStart(selected);
  const buttons = WEEKDAY_PREFIXES.map((prefix, offset) => {
    const iso = shiftDate(sunday, offset);
    const day = Number(iso.slice(8, 10));
    const style = iso === selected ? ' style="primary"' : "";
    return `<tg-button type="callback_data" data="day:${iso}"${style}>${prefix}${day}</tg-button>`;
  });
  return `<tg-button-row align="center">${buttons.join("")}</tg-button-row>`;
}

function navBar(selected: string): string {
  return (
    `<tg-button-row align="center">` +
    `<tg-button type="callback_data" data="day:${shiftDate(selected, -7)}">‹</tg-button>` +
    `<tg-button type="callback_data" data="day:today">today</tg-button>` +
    `<tg-button type="callback_data" data="day:${shiftDate(selected, 7)}">›</tg-button>` +
    `</tg-button-row>`
  );
}

// The server works in Asia/Jerusalem, which is ahead of UTC, so its date
// rolls over first. Deriving "today" from toISOString() here would drop the
// "· today" suffix for the first two or three hours of every local day.
// Read from VAULT_TIMEZONE (config.ts, same fallback as the server's
// VAULT_TIMEZONE default in apps/vault-server/src/config.py) rather than
// hardcoded: the two must agree, or this label silently diverges the moment
// either side's timezone changes.
function todayInVaultTimezone(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: config.vaultTimezone }).format(new Date());
}

export function buildDayRich(data: DailyResponse): InputRichMessage<InputFile> {
  const today = todayInVaultTimezone();
  const parts: string[] = [];

  parts.push(`<h2>${escapeHtml(headerLabel(data.date, today))}</h2>`);
  parts.push(
    `<p>${hours(data.coverage.covered_minutes)} covered · ` +
    `${hours(data.coverage.unaccounted_minutes)} unaccounted</p>`,
  );

  // Blocks and gaps interleave in time order: a gap is a hole between
  // blocks, so reading them as one sequence is the whole point.
  //
  // `elapsed_minutes` carries the "is it today" signal for free (past day
  // -> 1440, future day -> 0, today -> strictly between), so there is no
  // timezone comparison here — a row is "ahead" purely by comparing its
  // start to that number.
  const elapsedMinutes = data.coverage.elapsed_minutes;
  const rows = [
    ...data.blocks.map((b) => {
      const ahead = toMinutes(b.start) >= elapsedMinutes;
      return { at: b.start, ahead, html: blockRow(b, ahead) };
    }),
    // Gap rows never carry `⟳`: the server already excludes future time
    // from `unaccounted`, so a gap starting at or after `elapsed_minutes`
    // does not occur in practice, but the split still needs to place it on
    // the correct side if it ever did.
    ...data.gaps.map((g) => ({ at: g.start, ahead: toMinutes(g.start) >= elapsedMinutes, html: gapRow(g) })),
  ].sort((a, b) => a.at.localeCompare(b.at));

  if (rows.length === 0) {
    parts.push("<p>no blocks</p>");
  } else {
    // The divider only makes sense on today: on a past day everything is
    // elapsed, on a future day everything is ahead, and a rule that emits
    // above or below the whole table is noise rather than a divider.
    const isToday = elapsedMinutes > 0 && elapsedMinutes < MINUTES_PER_DAY;
    const elapsedRows = rows.filter((r) => !r.ahead);
    const aheadRows = rows.filter((r) => r.ahead);

    if (isToday && elapsedRows.length > 0 && aheadRows.length > 0) {
      parts.push(`<table>${elapsedRows.map((r) => r.html).join("")}</table>`);
      parts.push("<hr>");
      parts.push(`<table>${aheadRows.map((r) => r.html).join("")}</table>`);
    } else {
      parts.push(`<table>${rows.map((r) => r.html).join("")}</table>`);
    }
  }

  // Timed todos already appear above as blocks; showing them again here
  // would render the same commitment twice.
  const untimed = (data.todos ?? []).filter((t) => !t.scheduled_at);
  if (untimed.length > 0) {
    const items = untimed.map((t) => {
      const box = t.done ? '<input type="checkbox" checked>' : '<input type="checkbox">';
      const dur = t.duration_minutes != null ? ` (${t.duration_minutes}m)` : "";
      return `<li>${box}${escapeHtml(t.text)}${escapeHtml(dur)}</li>`;
    });
    parts.push(`<h3>☑️ Todos</h3>`);
    parts.push(`<ul>${items.join("")}</ul>`);
  }

  if (data.notes && data.notes.length > 0) {
    const items = data.notes.map((n) => {
      const text = n.text ?? (n.caption ? `📷 ${n.caption}` : "📷");
      return `<li>${escapeHtml(text)}</li>`;
    });
    parts.push(`<h3>📝 Notes</h3>`);
    parts.push(`<ul>${items.join("")}</ul>`);
  }

  parts.push(weekBar(data.date));
  parts.push(navBar(data.date));

  return { html: parts.join("\n") };
}
