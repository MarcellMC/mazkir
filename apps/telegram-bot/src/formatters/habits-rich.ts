import type { InputFile } from "grammy";
import type { InputRichMessage } from "@grammyjs/types";
import type { Habit } from "@mazkir/shared-types";
import { escapeHtml } from "./telegram.js";

/** Rich messages are authored as HTML here rather than markdown because
 *  button syntax (`<tg-button>`) has no markdown equivalent — the same
 *  reasoning as day-rich.ts, which this file is modelled on.
 *
 *  No partial progress (`1/2`) is rendered: `GET /habits` returns only
 *  `completed_today` and `streak`. `completions_today` and `daily_target`
 *  exist server-side in services/habit_completion.py and reach `/daily`'s
 *  blocks, but neither the habits route nor `@mazkir/shared-types`' `Habit`
 *  carries them. Surfacing progress here means extending both first. */

export function buildHabitsRich(habits: Habit[]): InputRichMessage<InputFile> {
  if (habits.length === 0) {
    return { html: "<h2>💪 No habits tracked yet.</h2>" };
  }

  const parts: string[] = ["<h2>💪 Habit Tracker</h2>"];

  const items = habits.map((h) => {
    const icon = h.completed_today ? "✅" : "⏳";
    return `<li>${icon} <b>${escapeHtml(h.name)}</b> — 🔥 ${h.streak} day streak</li>`;
  });
  parts.push(`<ul>${items.join("")}</ul>`);

  const avgStreak = Math.round(habits.reduce((s, h) => s + h.streak, 0) / habits.length);
  parts.push(`<p>📊 Average streak: <b>${avgStreak} days</b></p>`);

  // One button per still-pending habit, one per row: unlike the task list,
  // the label has to name which habit it completes, and full-width labels
  // side by side would truncate. Habits already done get no button — there
  // is nothing left to do to them, and a row of them would be dead weight.
  //
  // `habit:complete:` carries the habit NAME, not a slug, because the server
  // resolves by name. escapeHtml applies to the data attribute as well as
  // the label: an unescaped `<` or `&` in a name would break the surrounding
  // markup, and Telegram decodes the entity back before the callback fires.
  const pending = habits.filter((h) => !h.completed_today);
  for (const h of pending) {
    const name = escapeHtml(h.name);
    parts.push(
      `<tg-button-row align="center">` +
      `<tg-button type="callback_data" data="habit:complete:${name}" style="success">✅ ${name}</tg-button>` +
      `</tg-button-row>`,
    );
  }

  return { html: parts.join("\n") };
}
