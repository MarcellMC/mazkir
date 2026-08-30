import { Composer } from "grammy";
import { api } from "../api/client.js";
import { formatHabits } from "../formatters/telegram.js";
import { buildHabitsKeyboard } from "../keyboards/habits.js";
import type { Habit } from "@mazkir/shared-types";

export const habitsCommand = new Composer();

habitsCommand.command("habits", async (ctx) => {
  try {
    const habits: Habit[] = await api.listHabits();
    const text = formatHabits(habits);
    const kb = buildHabitsKeyboard(habits);

    await ctx.reply(text, { parse_mode: "HTML", reply_markup: kb });
  } catch {
    await ctx.reply("❌ Failed to load habits.");
  }
});
