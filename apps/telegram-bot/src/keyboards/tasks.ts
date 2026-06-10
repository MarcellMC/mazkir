import { InlineKeyboard } from "grammy";
import type { Task } from "@mazkir/shared-types";

/** Telegram hard-limits callback_data to 64 bytes; our prefixes use 10. */
const SLUG_BUDGET_BYTES = 54;

/**
 * Stable short id for a task: the vault filename stem, truncated to fit
 * Telegram's callback_data limit. The server resolves truncated slugs by
 * prefix match.
 */
export function taskSlug(task: Task): string {
  const stem = task.path
    ? task.path.split("/").pop()!.replace(/\.md$/, "")
    : task.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  let slug = stem;
  while (Buffer.byteLength(slug, "utf8") > SLUG_BUDGET_BYTES) {
    slug = slug.slice(0, -1);
  }
  return slug;
}

/** One button per task — tapping shows the task detail view. */
export function buildTasksKeyboard(tasks: Task[], limit = 8): InlineKeyboard {
  const kb = new InlineKeyboard();
  for (const t of tasks.slice(0, limit)) {
    kb.text(`👀 ${t.name}`, `task:view:${taskSlug(t)}`).row();
  }
  return kb;
}

/** Detail view actions: complete this task, or go back to the list. */
export function buildTaskDetailKeyboard(slug: string): InlineKeyboard {
  return new InlineKeyboard()
    .text("✅ Complete", `task:done:${slug}`)
    .text("⬅️ Back to list", "nav:tasks");
}
