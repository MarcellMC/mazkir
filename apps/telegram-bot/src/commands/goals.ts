import { Composer } from "grammy";
import { api } from "../api/client.js";
import { formatGoals } from "../formatters/telegram.js";
import { buildGoalsKeyboard } from "../keyboards/goals.js";
import { logger } from "../logger.js";
import { markActiveSpanError } from "../tracing-utils.js";
import type { Goal } from "@mazkir/shared-types";

export const goalsCommand = new Composer();

goalsCommand.command("goals", async (ctx) => {
  try {
    const goals: Goal[] = await api.listGoals();
    const text = formatGoals(goals);
    const kb = buildGoalsKeyboard(goals);

    await ctx.reply(text, { parse_mode: "HTML", reply_markup: kb });
  } catch (err) {
    markActiveSpanError(err);
    logger.error({ event_type: "command_failed", command: "goals", err: String(err) }, "command_failed");
    await ctx.reply("❌ Failed to load goals.");
  }
});
