import { Composer } from "grammy";
import { api } from "../api/client.js";
import { formatGoals } from "../formatters/telegram.js";
import type { Goal } from "@mazkir/shared-types";

export const goalsCommand = new Composer();

goalsCommand.command("goals", async (ctx) => {
  try {
    const goals: Goal[] = await api.listGoals();
    await ctx.reply(formatGoals(goals), { parse_mode: "HTML" });
  } catch {
    await ctx.reply("❌ Failed to load goals.");
  }
});
