import type { InputFile } from "grammy";
import type { InputRichMessage } from "@grammyjs/types";
import type { Goal, GoalDetail, GoalPriority } from "@mazkir/shared-types";
import { escapeHtml, progressBar, stripEmptySections } from "./telegram.js";
import { goalSlug } from "../keyboards/goals.js";

/** Rich messages are authored as HTML here rather than markdown because
 *  button syntax (`<tg-button>`) has no markdown equivalent — the same
 *  reasoning as day-rich.ts, which this file is modelled on. */

const DETAIL_BODY_MAX = 800;

/** Telegram allows 1–8 buttons in a `<tg-button-row>`, and that is also the
 *  cap on how many goals get a button: past that the message stops being
 *  scannable, and the body says how many were left out. */
const MAX_BUTTONS = 8;

function priorityEmoji(priority: number): string {
  if (priority >= 4) return "🔴";
  if (priority === 3) return "🟡";
  return "🟢";
}

/** Goals store priority as "high" | "medium" | "low" (older payloads used the
 *  numeric 1-5 scale); map those onto the numeric scale before picking an
 *  emoji. Moved here from telegram.ts along with the rest of the goal
 *  rendering — nothing outside this file needs it. */
function goalPriorityEmoji(priority: GoalPriority): string {
  if (typeof priority === "number") return priorityEmoji(priority);
  const scale: Record<string, number> = { high: 5, medium: 3, low: 1 };
  return priorityEmoji(scale[priority.toLowerCase()] ?? 3);
}

/** Button labels are the list number, not the goal name. Bot API renders a
 *  row's buttons side by side, so eight name-width buttons would each be
 *  unreadably narrow; the body already carries the names against the same
 *  numbers, and labels take plain text only. */
function buttonRows(goals: Goal[]): string[] {
  const rows: string[] = [];
  for (let i = 0; i < goals.length; i += MAX_BUTTONS) {
    const buttons = goals.slice(i, i + MAX_BUTTONS).map((g, j) =>
      `<tg-button type="callback_data" data="goal:view:${goalSlug(g)}">${i + j + 1}</tg-button>`,
    );
    rows.push(`<tg-button-row align="center">${buttons.join("")}</tg-button-row>`);
  }
  return rows;
}

export function buildGoalsRich(goals: Goal[]): InputRichMessage<InputFile> {
  if (goals.length === 0) {
    return { html: "<h2>🎯 No active goals.</h2>" };
  }

  // The server already returns goals sorted by priority then progress, so the
  // body order — and therefore the button numbering — matches what it sent.
  // The body lists exactly what has a button: listing the tail as well and
  // then adding "…and N more" was false, and showed goals nothing could open.
  const shown = goals.slice(0, MAX_BUTTONS);
  const parts: string[] = ["<h2>🎯 Goals</h2>"];

  const items = shown.map((g, i) => {
    const emoji = goalPriorityEmoji(g.priority);
    const target = g.target_date ? `<br>   📅 Target: ${escapeHtml(g.target_date)}` : "";
    return (
      `<li>${emoji} <b>${i + 1}. ${escapeHtml(g.name)}</b><br>` +
      `   ${progressBar(g.progress)} ${g.progress}%${target}</li>`
    );
  });
  parts.push(`<ul>${items.join("")}</ul>`);

  if (goals.length > shown.length) {
    parts.push(`<p>…and ${goals.length - shown.length} more</p>`);
  }

  parts.push(...buttonRows(shown));
  return { html: parts.join("\n") };
}

export function buildGoalDetailRich(goal: GoalDetail): InputRichMessage<InputFile> {
  const parts: string[] = [`<h2>🎯 ${escapeHtml(goal.name)}</h2>`];

  const lines: string[] = [
    `${progressBar(goal.progress)} ${goal.progress}%`,
    `${goalPriorityEmoji(goal.priority)} Priority: <b>${escapeHtml(String(goal.priority))}</b>`,
    `📌 Status: ${escapeHtml(goal.status)}`,
  ];
  if (goal.category) lines.push(`🏷 Category: ${escapeHtml(goal.category)}`);
  if (goal.start_date) lines.push(`🕐 Started: ${escapeHtml(String(goal.start_date))}`);
  if (goal.target_date) lines.push(`📅 Target: ${escapeHtml(String(goal.target_date))}`);
  parts.push(`<p>${lines.join("<br>")}</p>`);

  // Milestone entries are free-form in the vault; render the plain-string
  // ones and leave anything richer to the note body below.
  const milestones = (goal.milestones ?? []).filter((m) => typeof m === "string");
  if (milestones.length > 0) {
    parts.push("<h3>🚩 Milestones</h3>");
    parts.push(`<ul>${milestones.map((m) => `<li>${escapeHtml(m)}</li>`).join("")}</ul>`);
  }

  // `content` is optional on the wire, so guard it — stripEmptySections
  // takes a string.
  const body = goal.content ? stripEmptySections(goal.content) : "";
  if (body) {
    const truncated =
      body.length > DETAIL_BODY_MAX ? body.slice(0, DETAIL_BODY_MAX) + "…" : body;
    parts.push(`<blockquote>${escapeHtml(truncated)}</blockquote>`);
  }

  // Back only: goals have no completion endpoint.
  parts.push(
    `<tg-button-row align="center">` +
    `<tg-button type="callback_data" data="nav:goals">⬅️ Back to list</tg-button>` +
    `</tg-button-row>`,
  );
  return { html: parts.join("\n") };
}
