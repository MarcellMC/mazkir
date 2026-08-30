import { InlineKeyboard } from "grammy";

export type ViewName = "day" | "tasks" | "habits" | "goals";

const VIEWS: { name: ViewName; label: string }[] = [
  { name: "day", label: "📅 Day" },
  { name: "tasks", label: "📋 Tasks" },
  { name: "habits", label: "💪 Habits" },
  { name: "goals", label: "🎯 Goals" },
];

/** The cross-view keyboard: where you can go from here.
 *
 *  This is the ONLY thing that belongs in a view's `reply_markup`. Anything
 *  that navigates *within* a view — opening a task, completing a habit,
 *  changing the day — goes in the message body as a `<tg-button-row>`, so
 *  the two kinds of control stay visually distinct.
 *
 *  The current view is omitted rather than disabled: a button that re-renders
 *  the message you are already looking at makes Telegram reject the edit as
 *  "not modified", which is a no-op the bot then has to special-case.
 *
 *  No Calendar button — `/day` already renders calendar-derived blocks
 *  directly, so a separate calendar view would just be a second view of the
 *  same data, and `/calendar` remains its own command for that. */
export function buildNavKeyboard(current: ViewName): InlineKeyboard {
  const kb = new InlineKeyboard();
  for (const v of VIEWS) {
    if (v.name === current) continue;
    kb.text(v.label, `nav:${v.name}`);
  }
  return kb;
}
