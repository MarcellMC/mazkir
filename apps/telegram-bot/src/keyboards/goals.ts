import { InlineKeyboard } from "grammy";
import type { Goal } from "@mazkir/shared-types";
import { callbackSlug } from "./slug.js";

/** Stable short id for a goal — the vault filename stem. */
export function goalSlug(goal: Goal): string {
  return callbackSlug(goal);
}

/**
 * One button per goal — tapping shows the goal detail view. The server
 * already returns goals sorted by priority then progress, so the order here
 * matches the order of the message body.
 */
export function buildGoalsKeyboard(goals: Goal[], limit = 8): InlineKeyboard {
  const kb = new InlineKeyboard();
  goals.slice(0, limit).forEach((g, i) => {
    // `.row()` before rather than after, so the last button doesn't leave a
    // trailing blank row behind it.
    if (i > 0) kb.row();
    kb.text(`${i + 1}. ${g.name}`, `goal:view:${goalSlug(g)}`);
  });
  // Cross-view nav, always on its own row at the bottom. This mixes an
  // in-view control (the goal buttons above) with a cross-view one in a
  // single keyboard — an interim; separating them needs this view to become
  // a rich message like /day, which is queued as separate work.
  kb.row().text("📅 Day", "nav:day");
  return kb;
}

/** Detail view actions. Goals have no completion endpoint, so: back only. */
export function buildGoalDetailKeyboard(): InlineKeyboard {
  return new InlineKeyboard().text("⬅️ Back to list", "nav:goals");
}
