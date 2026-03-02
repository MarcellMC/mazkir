import { Composer, InlineKeyboard } from "grammy";
import { api } from "../api/client.js";
import { formatDay } from "../formatters/telegram.js";

export const dayCommand = new Composer();

dayCommand.command("day", async (ctx) => {
  try {
    const data = await api.getDaily();
    const kb = new InlineKeyboard()
      .text("📋 Tasks", "nav:tasks")
      .text("💪 Habits", "nav:habits")
      .row()
      .text("🎯 Goals", "nav:goals")
      .text("📅 Calendar", "nav:calendar");

    await ctx.reply(formatDay(data), { parse_mode: "HTML", reply_markup: kb });
  } catch {
    await ctx.reply("❌ Failed to load daily summary. Is vault-server running?");
  }
});
