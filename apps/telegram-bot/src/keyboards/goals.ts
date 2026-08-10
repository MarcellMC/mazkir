import { InlineKeyboard } from "grammy";
import type { Goal } from "@mazkir/shared-types";

/** Telegram hard-limits callback_data to 64 bytes; our prefixes use 10. */
const SLUG_BUDGET_BYTES = 54;

/**
 * Stable short id for a goal: the vault filename stem, truncated to fit
 * Telegram's callback_data limit. The server resolves truncated slugs by
 * prefix match.
 */
export function goalSlug(goal: Goal): string {
  const stem = goal.path
    ? goal.path.split("/").pop()!.replace(/\.md$/, "")
    : goal.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  let slug = stem;
  while (Buffer.byteLength(slug, "utf8") > SLUG_BUDGET_BYTES) {
    slug = slug.slice(0, -1);
  }
  return slug;
}

/** One button per goal — tapping shows the goal detail view. */
export function buildGoalsKeyboard(goals: Goal[], limit = 8): InlineKeyboard {
  const kb = new InlineKeyboard();
  goals.slice(0, limit).forEach((g, i) => {
    kb.text(`${i + 1}. ${g.name}`, `goal:view:${goalSlug(g)}`).row();
  });
  return kb;
}

/** Detail view actions: back to the goals list. */
export function buildGoalDetailKeyboard(): InlineKeyboard {
  return new InlineKeyboard().text("⬅️ Back to list", "nav:goals");
}
