import type { InputFile } from "grammy";
import type { InputRichMessage } from "@grammyjs/types";
import type { DailyBlock } from "@mazkir/shared-types";
import { escapeHtml } from "./telegram.js";

/** Step sizes, largest first so the magnitudes align in columns with the
 *  biggest on the outside — chosen from on-device renders (spec §6.1). */
export const NUDGES = [30, 15, 5];

function button(label: string, data: string, style?: string): string {
  const s = style ? ` style="${style}"` : "";
  return `<tg-button type="callback_data" data="${data}"${s}>${label}</tg-button>`;
}

function toMinutes(hhmmStr: string): number {
  const [h, m] = hhmmStr.split(":").map(Number);
  return (h ?? 0) * 60 + (m ?? 0);
}

function toClock(minutes: number): string {
  // Wraps rather than clamps: nudging past midnight is a real edit, and the
  // server decides whether the result is legal.
  const m = ((minutes % 1440) + 1440) % 1440;
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

/** One field's two nudge rows, inside a single `<td>`.
 *
 *  Two explicit rows rather than one row of six: at phone width Telegram wraps
 *  six buttons to 3+3 on its own, so pinning the arrangement means emitting
 *  the rows ourselves.
 *
 *  Each button carries the *accumulated* draft, not its own step — that is
 *  what lets the offsets live in the callback data instead of on the server
 *  (spec §6.2), so there is no edit state to evict and a button on an old
 *  message cannot apply its offsets to something since changed. */
function nudgePad(
  id: string, date: string, field: "start" | "end",
  startDelta: number, endDelta: number,
): string {
  const rows = [-1, 1].map((sign) =>
    "<tg-button-row>" +
    NUDGES.map((step) => {
      const delta = sign * step;
      const nextStart = field === "start" ? startDelta + delta : startDelta;
      const nextEnd = field === "end" ? endDelta + delta : endDelta;
      const label = `${sign < 0 ? "−" : "+"}${step}`;
      return button(label, `adj:${date}:${id}:${nextStart}:${nextEnd}`);
    }).join("") +
    "</tg-button-row>",
  );
  return `<td>${rows.join("")}</td>`;
}

export function buildBlockEditRich(
  block: DailyBlock, date: string, startDelta: number, endDelta: number,
): InputRichMessage<InputFile> {
  const start = toClock(toMinutes(block.start) + startDelta);
  const end = toClock(toMinutes(block.end) + endDelta);
  const length = ((toMinutes(end) - toMinutes(start)) + 1440) % 1440;

  const parts: string[] = [
    `<h2>${escapeHtml(block.title)}</h2>`,
    `<p>${start} – ${end} · ${length}m · ${escapeHtml(block.source)}</p>`,
    "<table>" +
      `<tr><td>start ${start}</td>${nudgePad(block.id, date, "start", startDelta, endDelta)}</tr>` +
      `<tr><td>end ${end}</td>${nudgePad(block.id, date, "end", startDelta, endDelta)}</tr>` +
    "</table>",
    "<p><i>nothing is written until you save</i></p>",
    // One button, not two: bothering to fix the times is taken as
    // confirmation that it happened (spec §6.2).
    `<tg-button-row align="center">` +
      button("✓ save &amp; approve", `adjsave:${date}:${block.id}:${startDelta}:${endDelta}`, "success") +
      button("← back", `day:${date}`) +
    "</tg-button-row>",
    "<h3>this event</h3>",
    // Rendered but inert in this ship (spec §6.3, §9). Drawn because the
    // layout was approved with them present and their absence reads as an
    // unfinished view; they answer with a toast saying they are not wired up.
    "<tg-button-row>" +
      button("cancel in calendar", `cal:cancel:${block.id}`) +
      button("delete", `cal:delete:${block.id}`, "danger") +
    "</tg-button-row>",
  ];

  // No rename button: Ship 4 already renames by talking, and a button whose
  // only power is to open a text prompt is not an improvement on saying it.
  return { html: parts.join("\n") };
}
