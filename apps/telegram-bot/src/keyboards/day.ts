import { InlineKeyboard } from "grammy";

/**
 * Cross-view navigation for `/day`: Tasks / Habits / Goals. No Calendar
 * button — `/day` already renders calendar-derived blocks directly, so a
 * separate calendar view would just be a second view of the same data, and
 * `/calendar` remains its own command for that.
 *
 * This lives in one shared place because both `commands/day.ts` (initial
 * send) and the `day:` callback handler (re-render on date navigation) need
 * the identical keyboard attached — duplicating the builder in both call
 * sites would let them drift.
 */
export function buildDayNavKeyboard(): InlineKeyboard {
  return new InlineKeyboard()
    .text("📋 Tasks", "nav:tasks")
    .text("💪 Habits", "nav:habits")
    .text("🎯 Goals", "nav:goals");
}
