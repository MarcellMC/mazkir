import { Composer } from "grammy";
import { api } from "../api/client.js";
import { formatTasks } from "../formatters/telegram.js";
import { buildTasksKeyboard } from "../keyboards/tasks.js";
import { logger } from "../logger.js";
import { markActiveSpanError } from "../tracing-utils.js";
import type { Task } from "@mazkir/shared-types";

export const tasksCommand = new Composer();

tasksCommand.command("tasks", async (ctx) => {
  try {
    const tasks: Task[] = await api.listTasks();
    const text = formatTasks(tasks);
    const kb = buildTasksKeyboard(tasks);

    await ctx.reply(text, { parse_mode: "HTML", reply_markup: kb });
  } catch (err) {
    markActiveSpanError(err);
    logger.error({ event_type: "command_failed", command: "tasks", err: String(err) }, "command_failed");
    await ctx.reply("❌ Failed to load tasks.");
  }
});
