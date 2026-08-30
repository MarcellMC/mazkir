import { Composer } from "grammy";
import { api } from "../api/client.js";
import { buildHabitsRich } from "../formatters/habits-rich.js";
import { sendRich } from "../bot-utils/send-rich.js";
import { buildNavKeyboard } from "../keyboards/nav.js";
import { logger } from "../logger.js";
import { markActiveSpanError } from "../tracing-utils.js";
import type { Habit } from "@mazkir/shared-types";

export const habitsCommand = new Composer();

habitsCommand.command("habits", async (ctx) => {
  // Fetch, render and send report separately, as /day does, so a Telegram
  // send failure is not reported as a server outage.
  let habits: Habit[];
  try {
    habits = await api.listHabits();
  } catch (err) {
    markActiveSpanError(err);
    logger.error({ event_type: "command_failed", command: "habits", err: String(err) }, "command_failed");
    await ctx.reply("❌ Failed to load habits. Is vault-server running?");
    return;
  }
  let rich;
  try {
    rich = buildHabitsRich(habits);
  } catch (err) {
    markActiveSpanError(err);
    logger.error({ event_type: "command_failed", command: "habits", err: String(err) }, "command_failed");
    await ctx.reply("❌ Failed to render habits.");
    return;
  }
  try {
    await sendRich(ctx, rich, { reply_markup: buildNavKeyboard("habits") });
  } catch (err) {
    markActiveSpanError(err);
    logger.error({ event_type: "command_failed", command: "habits", err: String(err) }, "command_failed");
    await ctx.reply("❌ Failed to send habits.");
  }
});
