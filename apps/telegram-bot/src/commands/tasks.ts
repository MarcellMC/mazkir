import { Composer, InlineKeyboard } from "grammy";
import { api } from "../api/client.js";
import { formatTasks } from "../formatters/telegram.js";
import type { Task } from "@mazkir/shared-types";

export const tasksCommand = new Composer();

tasksCommand.command("tasks", async (ctx) => {
  try {
    const tasks: Task[] = await api.listTasks();
    const text = formatTasks(tasks);

    const kb = new InlineKeyboard();
    for (const t of tasks.slice(0, 5)) {
      kb.text(`✅ ${t.name}`, `task:complete:${t.name}`).row();
    }

    await ctx.reply(text, { parse_mode: "HTML", reply_markup: kb });
  } catch {
    await ctx.reply("❌ Failed to load tasks.");
  }
});
