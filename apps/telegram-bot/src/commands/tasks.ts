import { Composer } from "grammy";
import { api } from "../api/client.js";
import { buildTasksRich } from "../formatters/tasks-rich.js";
import { sendRich } from "../bot-utils/send-rich.js";
import { buildNavKeyboard } from "../keyboards/nav.js";
import { logger } from "../logger.js";
import { markActiveSpanError } from "../tracing-utils.js";
import type { Task } from "@mazkir/shared-types";

export const tasksCommand = new Composer();

tasksCommand.command("tasks", async (ctx) => {
  // Fetch, render and send report separately, as /day does: a single catch
  // around all three reports a Telegram send failure as a server outage and
  // points the user at the wrong cause.
  let tasks: Task[];
  try {
    tasks = await api.listTasks();
  } catch (err) {
    markActiveSpanError(err);
    logger.error({ event_type: "command_failed", command: "tasks", err: String(err) }, "command_failed");
    await ctx.reply("❌ Failed to load tasks. Is vault-server running?");
    return;
  }
  let rich;
  try {
    rich = buildTasksRich(tasks);
  } catch (err) {
    markActiveSpanError(err);
    logger.error({ event_type: "command_failed", command: "tasks", err: String(err) }, "command_failed");
    await ctx.reply("❌ Failed to render tasks.");
    return;
  }
  try {
    await sendRich(ctx, rich, { reply_markup: buildNavKeyboard("tasks") });
  } catch (err) {
    markActiveSpanError(err);
    logger.error({ event_type: "command_failed", command: "tasks", err: String(err) }, "command_failed");
    await ctx.reply("❌ Failed to send tasks.");
  }
});
