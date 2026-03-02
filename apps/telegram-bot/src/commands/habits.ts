import { Composer, InlineKeyboard } from "grammy";
import { api } from "../api/client.js";
import { formatHabits } from "../formatters/telegram.js";
import type { Habit } from "@mazkir/shared-types";

export const habitsCommand = new Composer();

habitsCommand.command("habits", async (ctx) => {
  try {
    const habits: Habit[] = await api.listHabits();
    const text = formatHabits(habits);

    const kb = new InlineKeyboard();
    for (const h of habits.filter((h) => !h.completed_today)) {
      kb.text(`✅ ${h.name}`, `habit:complete:${h.name}`).row();
    }

    await ctx.reply(text, { parse_mode: "HTML", reply_markup: kb });
  } catch {
    await ctx.reply("❌ Failed to load habits.");
  }
});
