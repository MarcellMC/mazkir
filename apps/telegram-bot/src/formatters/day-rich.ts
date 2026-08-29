import type { InputFile } from "grammy";
import type { InputRichMessage } from "@grammyjs/types";
import type { DailyResponse, DailyBlock, DailyGap } from "@mazkir/shared-types";
import { escapeHtml } from "./telegram.js";

/** Rich messages are authored as HTML here rather than markdown because
 *  button syntax (`<tg-button>`) has no markdown equivalent. That also means
 *  escapeHtml remains the right tool for user text — a miss renders wrong
 *  rather than losing the whole message, which is what HTML parse_mode did. */

const WEEK_RADIUS = 3;

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

function blockRow(b: DailyBlock): string {
  const facets = b.activity && b.category
    ? `${escapeHtml(b.activity)} × ${escapeHtml(b.category)}`
    : "";
  const marker = b.habit_progress ? escapeHtml(b.habit_progress) : facets;
  return `<tr><td>${b.start}–${b.end}</td><td>${escapeHtml(b.title)}</td><td>${marker}</td></tr>`;
}

function gapRow(g: DailyGap): string {
  return `<tr><td>⚠ ${g.start}–${g.end}</td><td>—</td><td>${hours(g.minutes)}</td></tr>`;
}

function weekBar(selected: string): string {
  const buttons: string[] = [];
  for (let offset = -WEEK_RADIUS; offset <= WEEK_RADIUS; offset++) {
    const iso = shiftDate(selected, offset);
    const day = Number(iso.slice(8, 10));
    const style = offset === 0 ? ' style="primary"' : "";
    buttons.push(
      `<tg-button type="callback_data" data="day:${iso}"${style}>${day}</tg-button>`,
    );
  }
  return `<tg-button-row align="center">${buttons.join("")}</tg-button-row>`;
}

function navBar(selected: string): string {
  return (
    `<tg-button-row align="center">` +
    `<tg-button type="callback_data" data="day:${shiftDate(selected, -1)}">◀</tg-button>` +
    `<tg-button type="callback_data" data="day:today">today</tg-button>` +
    `<tg-button type="callback_data" data="day:${shiftDate(selected, 1)}">▶</tg-button>` +
    `</tg-button-row>`
  );
}

export function buildDayRich(data: DailyResponse): InputRichMessage<InputFile> {
  const today = new Date().toISOString().slice(0, 10);
  const parts: string[] = [];

  parts.push(`<h2>${escapeHtml(headerLabel(data.date, today))}</h2>`);
  parts.push(
    `<p>${hours(data.coverage.covered_minutes)} covered · ` +
    `${hours(data.coverage.unaccounted_minutes)} unaccounted</p>`,
  );

  // Blocks and gaps interleave in time order: a gap is a hole between
  // blocks, so reading them as one sequence is the whole point.
  const rows = [
    ...data.blocks.map((b) => ({ at: b.start, html: blockRow(b) })),
    ...data.gaps.map((g) => ({ at: g.start, html: gapRow(g) })),
  ].sort((a, b) => a.at.localeCompare(b.at));

  if (rows.length === 0) {
    parts.push("<p>no blocks</p>");
  } else {
    parts.push(`<table>${rows.map((r) => r.html).join("")}</table>`);
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
    parts.push(`<ul>${items.join("")}</ul>`);
  }

  if (data.notes && data.notes.length > 0) {
    const items = data.notes.map((n) => {
      const text = n.text ?? (n.caption ? `📷 ${n.caption}` : "📷");
      return `<li>${escapeHtml(text)}</li>`;
    });
    parts.push(`<ul>${items.join("")}</ul>`);
  }

  parts.push(weekBar(data.date));
  parts.push(navBar(data.date));

  return { html: parts.join("\n") };
}
