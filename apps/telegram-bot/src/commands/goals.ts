import { Composer } from "grammy";
import { api } from "../api/client.js";
import { buildGoalsRich } from "../formatters/goals-rich.js";
import { sendRich } from "../bot-utils/send-rich.js";
import { buildNavKeyboard } from "../keyboards/nav.js";
import { logger } from "../logger.js";
import { markActiveSpanError } from "../tracing-utils.js";
import type { Goal } from "@mazkir/shared-types";

export const goalsCommand = new Composer();

goalsCommand.command("goals", async (ctx) => {
  // Fetch, render and send report separately, as /day does, so a Telegram
  // send failure is not reported as a server outage.
  let goals: Goal[];
  try {
    goals = await api.listGoals();
  } catch (err) {
    markActiveSpanError(err);
    logger.error({ event_type: "command_failed", command: "goals", err: String(err) }, "command_failed");
    await ctx.reply("❌ Failed to load goals. Is vault-server running?");
    return;
  }
  let rich;
  try {
    rich = buildGoalsRich(goals);
  } catch (err) {
    markActiveSpanError(err);
    logger.error({ event_type: "command_failed", command: "goals", err: String(err) }, "command_failed");
    await ctx.reply("❌ Failed to render goals.");
    return;
  }
  try {
    await sendRich(ctx, rich, { reply_markup: buildNavKeyboard("goals") });
  } catch (err) {
    markActiveSpanError(err);
    logger.error({ event_type: "command_failed", command: "goals", err: String(err) }, "command_failed");
    await ctx.reply("❌ Failed to send goals.");
  }
});
