import { Composer } from "grammy";
import { api } from "../api/client.js";
import { formatGoals } from "../formatters/telegram.js";
import { buildGoalsKeyboard } from "../keyboards/goals.js";
import type { Goal } from "@mazkir/shared-types";

export const goalsCommand = new Composer();

goalsCommand.command("goals", async (ctx) => {
  try {
    const goals: Goal[] = await api.listGoals();
    const kb = buildGoalsKeyboard(goals);
    await ctx.reply(formatGoals(goals), { parse_mode: "HTML", reply_markup: kb });
  } catch {
    await ctx.reply("❌ Failed to load goals.");
  }
});
