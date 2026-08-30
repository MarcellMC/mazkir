import type { InputFile } from "grammy";
import type { InputRichMessage } from "@grammyjs/types";
import type { Task, TaskDetail } from "@mazkir/shared-types";
import { escapeHtml, stripEmptySections } from "./telegram.js";
import { taskSlug } from "../keyboards/tasks.js";

/** Rich messages are authored as HTML here rather than markdown because
 *  button syntax (`<tg-button>`) has no markdown equivalent — the same
 *  reasoning as day-rich.ts, which this file is modelled on. */

const PRIORITY_ICONS: Record<number, string> = { 5: "🔴", 4: "🔴", 3: "🟡", 2: "🟢", 1: "🟢" };
const DETAIL_BODY_MAX = 800;

/** Telegram allows 1–8 buttons in a `<tg-button-row>`. Eight is also the cap
 *  on how many tasks get a button at all: past that the message stops being
 *  scannable, and the body says how many were left out. */
const MAX_BUTTONS = 8;

/** Priority order, highest first — the one array both the numbered body list
 *  and the numbered buttons read from, so button `3` always addresses the
 *  task the body printed as `3.`. Deriving them separately is how those two
 *  drift apart. */
function byPriority(tasks: Task[]): Task[] {
  return [
    ...tasks.filter((t) => t.priority >= 4),
    ...tasks.filter((t) => t.priority === 3),
    ...tasks.filter((t) => t.priority <= 2),
  ];
}

/** Button labels are the list number, not the task name. Bot API renders a
 *  row's buttons side by side, so eight name-width buttons would each be
 *  unreadably narrow; the body already carries the names against the same
 *  numbers. Labels take plain text only — no bold, no font size — so the
 *  number is the whole label. */
function buttonRows(tasks: Task[]): string[] {
  const rows: string[] = [];
  for (let i = 0; i < tasks.length; i += MAX_BUTTONS) {
    const buttons = tasks.slice(i, i + MAX_BUTTONS).map((t, j) =>
      `<tg-button type="callback_data" data="task:view:${taskSlug(t)}">${i + j + 1}</tg-button>`,
    );
    rows.push(`<tg-button-row align="center">${buttons.join("")}</tg-button-row>`);
  }
  return rows;
}

function group(title: string, tasks: Task[], startAt: number): string[] {
  if (tasks.length === 0) return [];
  const items = tasks.map((t, i) => {
    const due = t.due_date ? ` (due ${escapeHtml(String(t.due_date))})` : "";
    return `<li>${startAt + i}. ⏳ ${escapeHtml(t.name)}${due}</li>`;
  });
  return [`<h3>${title}</h3>`, `<ul>${items.join("")}</ul>`];
}

export function buildTasksRich(tasks: Task[]): InputRichMessage<InputFile> {
  if (tasks.length === 0) {
    return { html: "<h2>📋 No active tasks. Enjoy the calm!</h2>" };
  }

  const sorted = byPriority(tasks);
  const shown = sorted.slice(0, MAX_BUTTONS);

  const parts: string[] = ["<h2>📋 Active Tasks</h2>"];

  // Numbering runs across the groups so it matches the button labels, which
  // index into `sorted` as one sequence rather than restarting per group.
  const high = sorted.filter((t) => t.priority >= 4);
  const medium = sorted.filter((t) => t.priority === 3);
  const low = sorted.filter((t) => t.priority <= 2);
  parts.push(...group("🔴 High Priority", high, 1));
  parts.push(...group("🟡 Medium Priority", medium, high.length + 1));
  parts.push(...group("🟢 Low Priority", low, high.length + medium.length + 1));

  if (sorted.length > shown.length) {
    parts.push(`<p>…and ${sorted.length - shown.length} more</p>`);
  }

  parts.push(...buttonRows(shown));
  return { html: parts.join("\n") };
}

export function buildTaskDetailRich(task: TaskDetail): InputRichMessage<InputFile> {
  const parts: string[] = [`<h2>📋 ${escapeHtml(task.name)}</h2>`];

  const icon = PRIORITY_ICONS[task.priority] ?? "🟡";
  const lines: string[] = [`${icon} Priority: <b>${task.priority}</b>`];
  if (task.category) lines.push(`🏷 Category: ${escapeHtml(task.category)}`);
  if (task.due_date) lines.push(`📅 Due: ${escapeHtml(String(task.due_date))}`);
  lines.push(`📌 Status: ${escapeHtml(task.status)}`);
  if (task.tokens_on_completion != null) {
    lines.push(`🪙 Tokens on completion: ${task.tokens_on_completion}`);
  }
  if (task.created) lines.push(`🕐 Created: ${escapeHtml(String(task.created))}`);
  if (task.google_event_id) lines.push("📆 Synced to Google Calendar");
  parts.push(`<p>${lines.join("<br>")}</p>`);

  // Note body: drop the title heading (duplicates the name) and empty
  // template sections, keep everything the user actually wrote. `content` is
  // optional on the wire, so guard it — stripEmptySections takes a string.
  const body = task.content ? stripEmptySections(task.content) : "";
  if (body) {
    const truncated =
      body.length > DETAIL_BODY_MAX ? body.slice(0, DETAIL_BODY_MAX) + "…" : body;
    parts.push(`<blockquote>${escapeHtml(truncated)}</blockquote>`);
  }

  parts.push(
    `<tg-button-row align="center">` +
    `<tg-button type="callback_data" data="task:done:${task.slug}" style="success">✅ Complete</tg-button>` +
    `<tg-button type="callback_data" data="nav:tasks">⬅️ Back to list</tg-button>` +
    `</tg-button-row>`,
  );
  return { html: parts.join("\n") };
}
