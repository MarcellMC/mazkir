import type { InputFile } from "grammy";
import type { InputRichMessage } from "@grammyjs/types";
import type { DailyResponse, DailyBlock, DailyGap, DailyIncomplete } from "@mazkir/shared-types";
import { config } from "../config.js";
import { escapeHtml } from "./telegram.js";

/** Rich messages are authored as HTML here rather than markdown because
 *  button syntax (`<tg-button>`) has no markdown equivalent. That also means
 *  escapeHtml remains the right tool for user text — a miss renders wrong
 *  rather than losing the whole message, which is what HTML parse_mode did. */

// Sunday-first, matching the Hebrew week. Index 0 == Sunday (getUTCDay()'s
// own numbering) through index 6 == Saturday.
const WEEKDAY_LETTERS = ["א", "ב", "ג", "ד", "ה", "ו", "ש"];

// One icon per weekday position, Sunday->Saturday: red diamond opens the
// week, small diamonds carry the weekdays, the compass/diamond turns toward
// Friday, and the candle marks Shabbat. Replaces a "✨ש" prefix that used to
// widen Saturday's button past the others and wrap onto a second line.
const WEEKDAY_ICONS = ["♦️", "🔸", "🔸", "🔸", "🔸", "💠", "🕯"];

// LRI/PDI (U+2066/U+2069) and the hyphenation point (U+2027, not the middot
// U+00B7 the user rejected) are all invisible in a diff or terminal. Hebrew
// is a strong-RTL script, so a bare "30‧א" reorders to display as "א‧30" —
// the isolate pair pins the date to the left by containing bidi reordering
// to just this run, without the side effects of an override (LRO) or mark
// (LRM). Drop any of the three and the label silently reverts to
// letter-first, or the wrap comes back, with nothing failing to signal it.
const LRI = "⁦";
const PDI = "⁩";
const HYPHENATION_POINT = "‧";

// The four states a row can be in, as exactly the characters chosen from
// on-device renders (spec §5.1). Not emoji-presentation variants: `⚠` used to
// render at a size that dominated the row, which is why it is gone.
//
// `✓` folds in what used to be `✅` (completed). The two occupied the same
// slot with nearly the same meaning, and where they diverged — a Google entry
// Google marks green, which is `completed` yet machine-inferred — the honest
// answer is `●`, because "the source says it was done" is one input to
// approval, not approval itself.
export const GLYPH_CONFIRMED = "✓";   // U+2713 — settled, counts
export const GLYPH_PENDING = "●";     // U+25CF — happened, waiting on you
export const GLYPH_GAP = "░";         // U+2591 — unaccounted
export const GLYPH_AHEAD = "◌";       // U+25CC — still ahead, no buttons

// A centred table cell is the only centring the rich grammar offers: `<p>` has
// no alignment at all, which is why the old `─`-run divider only looked
// centred when the dash count happened to match the message width, and drifted
// whenever it did not. `<sub>` shrinks it; middle dots thin it.
export const NOW_DIVIDER =
  '<table><tr><td align="center"><sub>' +
  "·".repeat(12) + " now " + "·".repeat(12) +
  "</sub></td></tr></table>";

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

function button(label: string, data: string, style?: string): string {
  const s = style ? ` style="${style}"` : "";
  return `<tg-button type="callback_data" data="${data}"${s}>${label}</tg-button>`;
}

/** A `<tg-button-row>` wrapped in the `<td>` it must live in. Buttons only
 *  render as compact pills inside a cell — at top level the row stretches to
 *  full width, and inside an `<li>` Telegram hoists it out of the list and
 *  stretches it anyway. Verified on device 2026-09-10. */
function cellButtons(...buttons: string[]): string {
  return `<td><tg-button-row>${buttons.join("")}</tg-button-row></td>`;
}

function blockRow(b: DailyBlock, ahead: boolean, date: string): string {
  const glyph = ahead
    ? GLYPH_AHEAD
    : b.state === "approved" ? GLYPH_CONFIRMED : GLYPH_PENDING;
  const time = `<td>${glyph} ${b.start}–${b.end}</td>`;
  const title = `<td>${escapeHtml(b.title)}</td>`;
  const marker = b.habit_progress ? escapeHtml(b.habit_progress) : facetLabel(b);

  // A still-ahead block gets no controls: it has not happened, so there is
  // nothing to confirm. That is what the `◌` is explaining.
  if (ahead || b.state !== "pending") {
    // Pending rows spend the third column on controls; approved rows spend it
    // on the facet label. The two are mutually exclusive, so the column never
    // holds both and the table stays three columns wide. Until Ship 6
    // populates activity/category that cell is usually empty on an approved
    // row, which matches the pre-Ship-5 rendering.
    return `<tr>${time}${title}<td>${marker}</td></tr>`;
  }

  // The date rides in the callback because the button must address the day it
  // was drawn for. Deriving "today" in the handler instead would make every
  // control on a browsed day act on the wrong date.
  return `<tr>${time}${title}${cellButtons(
    button(GLYPH_CONFIRMED, `block:approve:${date}:${b.id}`, "success"),
    button("✕", `block:dismiss:${date}:${b.id}`, "danger"),
    button("✎", `block:edit:${date}:${b.id}`),
  )}</tr>`;
}

function gapRow(g: DailyGap, date: string): string {
  const start = toMinutes(g.start);
  // `end` may be "24:00" — day_coverage emits it for a gap running to end of
  // day. toMinutes handles it arithmetically (1440), which is what the fill
  // endpoint wants anyway.
  const end = toMinutes(g.end);
  const time = `<td>${GLYPH_GAP} ${g.start}–${g.end}</td>`;

  if (g.proposal) {
    // A proposal is a question with a ✕ beside it, so it carries the same
    // controls as a pending block. The day count is shown so the guess can be
    // judged rather than trusted.
    // `days_seen: 0` is the overnight cold-start seed, not an observation —
    // gap_proposals.py returns it when a gap contains the core of the night
    // and history has nothing to say. Rendering it as "0/14" read as
    // "never seen this", which argues against the very guess it labels, so
    // the seed says what it is instead of showing a count it does not have.
    const seen = g.proposal.days_seen > 0
      ? `${g.proposal.days_seen}/14`
      : "a guess";
    return `<tr>${time}<td>${escapeHtml(g.proposal.name)}? <sub>${seen}</sub></td>` +
      cellButtons(
        button(GLYPH_CONFIRMED, `prop:approve:${date}:${start}:${end}`, "success"),
        button("✕", `prop:dismiss:${date}:${start}:${end}`, "danger"),
        button("✎", `prop:edit:${date}:${start}:${end}`),
      ) + "</tr>";
  }

  return `<tr>${time}<td>—</td>` + cellButtons(
    button(`+ ${hours(g.minutes)}`, `gap:fill:${date}:${start}:${end}`),
  ) + "</tr>";
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
 *  superscript, or font-size markup available to mark Saturday gold; the
 *  per-day icon (see WEEKDAY_ICONS) is the deliberate substitute. Each label
 *  is two lines joined by a literal "\n" — icon on top, date+letter below —
 *  which Bot API renders as a line break inside the button. A single-line
 *  "✨ש5" label used to wrap onto a second line on-device because the
 *  sparkle made Saturday's label wider than the others; splitting the icon
 *  onto its own line removes the width mismatch that caused the wrap. */
function weekBar(selected: string): string {
  const sunday = weekStart(selected);
  const buttons = WEEKDAY_LETTERS.map((letter, offset) => {
    const iso = shiftDate(sunday, offset);
    const day = Number(iso.slice(8, 10));
    const icon = WEEKDAY_ICONS[offset];
    const style = iso === selected ? ' style="success"' : "";
    const label = `${icon}\n${LRI}${day}${HYPHENATION_POINT}${letter}${PDI}`;
    return `<tg-button type="callback_data" data="day:${iso}"${style}>${label}</tg-button>`;
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

  // The summary and the refresh button share a one-row table, because
  // `<td align="right">` is the only right-alignment the rich grammar offers.
  // The `<h2>` stays outside it: table cells take inline formatting only, so
  // a heading inside one degrades to bold body text.
  parts.push(
    "<table><tr>" +
    `<td><sub>${hours(data.coverage.confirmed_minutes)} confirmed · ` +
    `${hours(data.coverage.pending_minutes)} pending · ` +
    `${hours(data.coverage.unaccounted_minutes)} unaccounted</sub></td>` +
    `<td align="right"><tg-button-row>` +
    button("⟲", `day:refresh:${data.date}`) +
    "</tg-button-row></td>" +
    "</tr></table>",
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
      return { at: b.start, ahead, html: blockRow(b, ahead, data.date) };
    }),
    // Gap rows never carry `◌`: the server already excludes future time
    // from `unaccounted`, so a gap starting at or after `elapsed_minutes`
    // does not occur in practice, but the split still needs to place it on
    // the correct side if it ever did.
    ...data.gaps.map((g) => ({ at: g.start, ahead: toMinutes(g.start) >= elapsedMinutes, html: gapRow(g, data.date) })),
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
      parts.push(NOW_DIVIDER);
      parts.push(`<table>${aheadRows.map((r) => r.html).join("")}</table>`);
    } else {
      parts.push(`<table>${rows.map((r) => r.html).join("")}</table>`);
    }
  }

  // The count is in the label deliberately: approve-all includes gap
  // proposals (spec §5.6), so the number tells you how many things it will
  // actually act on rather than hiding them behind the word "all". Only
  // elapsed pending blocks count — a still-ahead one has no buttons and
  // approve-all skips it server-side too.
  const pendingCount =
    data.blocks.filter(
      (b) => b.state === "pending" && toMinutes(b.start) < elapsedMinutes,
    ).length +
    data.gaps.filter((g) => g.proposal !== null).length;
  if (pendingCount > 0) {
    parts.push(
      `<p>&nbsp;</p><tg-button-row align="center">` +
      button(
        `${GLYPH_CONFIRMED} approve all ${pendingCount}`,
        `day:approveall:${data.date}`,
        "primary",
      ) +
      "</tg-button-row>",
    );
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

  // Read-only text, no buttons: a block is completed by talking, and a
  // button that opens a conversation is machinery this view does not need.
  const incomplete = data.incomplete ?? [];
  if (incomplete.length > 0) {
    const items = incomplete.map((b: DailyIncomplete) => {
      const known = b.start ? `started ${b.start}` : b.end ? `ended ${b.end}` : "no times";
      const want = b.missing.includes("start_time") ? "no start time" : "no end time";
      return `<li>⁇ <b>${escapeHtml(b.title)}</b> — ${escapeHtml(known)}, ${escapeHtml(want)}</li>`;
    });
    parts.push(`<h3>⁇ Needs a time</h3>`);
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

  // One rule for all navigation, week bar and nav grouped beneath it. This
  // removes an `<hr>` rather than adding one: with two rules in the message
  // the now divider stopped being unambiguous, which is what the comment on
  // this divider's predecessor recorded.
  parts.push("<p>&nbsp;</p><hr>");
  parts.push(weekBar(data.date));
  parts.push("<p>&nbsp;</p>");
  parts.push(navBar(data.date));

  return { html: parts.join("\n") };
}
