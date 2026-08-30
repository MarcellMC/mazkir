import { InlineKeyboard } from "grammy";
import type { Task } from "@mazkir/shared-types";
import { callbackSlug } from "./slug.js";

/** Stable short id for a task — the vault filename stem. */
export function taskSlug(task: Task): string {
  return callbackSlug(task);
}

/** One button per task — tapping shows the task detail view. */
export function buildTasksKeyboard(tasks: Task[], limit = 8): InlineKeyboard {
  const kb = new InlineKeyboard();
  const sorted = [
    ...tasks.filter((t) => t.priority >= 4),
    ...tasks.filter((t) => t.priority === 3),
    ...tasks.filter((t) => t.priority <= 2),
  ];
  sorted.slice(0, limit).forEach((t, i) => {
    // `.row()` before rather than after, so the last button doesn't leave a
    // trailing blank row behind it.
    if (i > 0) kb.row();
    kb.text(`${i + 1}. ${t.name}`, `task:view:${taskSlug(t)}`);
  });
  // Cross-view nav, always on its own row at the bottom. This mixes an
  // in-view control (the task buttons above) with a cross-view one in a
  // single keyboard — an interim; separating them needs this view to become
  // a rich message like /day, which is queued as separate work.
  kb.row().text("📅 Day", "nav:day");
  return kb;
}

/** Detail view actions: complete this task, or go back to the list. */
export function buildTaskDetailKeyboard(slug: string): InlineKeyboard {
  return new InlineKeyboard()
    .text("✅ Complete", `task:done:${slug}`)
    .text("⬅️ Back to list", "nav:tasks");
}
