import { InlineKeyboard } from "grammy";
import type { Habit } from "@mazkir/shared-types";

/**
 * One "complete" button per not-yet-completed habit, plus the cross-view
 * Day button on its own row at the bottom. Shared between `/habits` and the
 * `nav:habits` callback so both renders stay identical.
 */
export function buildHabitsKeyboard(habits: Habit[]): InlineKeyboard {
  const kb = new InlineKeyboard();
  for (const h of habits.filter((h) => !h.completed_today)) {
    kb.text(`✅ ${h.name}`, `habit:complete:${h.name}`).row();
  }
  // Cross-view nav, always on its own row at the bottom. This mixes an
  // in-view control (the completion buttons above) with a cross-view one in
  // a single keyboard — an interim; separating them needs this view to
  // become a rich message like /day, which is queued as separate work.
  kb.text("📅 Day", "nav:day");
  return kb;
}
