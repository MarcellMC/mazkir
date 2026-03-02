import { Composer } from "grammy";
import { api } from "../api/client.js";
import { formatTasks, formatHabits, formatCalendar, formatGoals } from "../formatters/telegram.js";

export const callbackHandlers = new Composer();

// Habit completion
callbackHandlers.callbackQuery(/^habit:complete:(.+)$/, async (ctx) => {
  const name = ctx.match[1]!;
  try {
    await api.completeHabit(name);
    await ctx.answerCallbackQuery({ text: `✅ ${name} completed!` });
    // Refresh the habits list in-place
    const habits = await api.listHabits();
    await ctx.editMessageText(formatHabits(habits), { parse_mode: "HTML" });
  } catch {
    await ctx.answerCallbackQuery({ text: "❌ Failed to complete habit" });
  }
});

// Task completion
callbackHandlers.callbackQuery(/^task:complete:(.+)$/, async (ctx) => {
  const name = ctx.match[1]!;
  try {
    await api.completeTask(name);
    await ctx.answerCallbackQuery({ text: `✅ ${name} completed!` });
    const tasks = await api.listTasks();
    await ctx.editMessageText(formatTasks(tasks), { parse_mode: "HTML" });
  } catch {
    await ctx.answerCallbackQuery({ text: "❌ Failed to complete task" });
  }
});

// Navigation
callbackHandlers.callbackQuery(/^nav:(.+)$/, async (ctx) => {
  const target = ctx.match[1];
  await ctx.answerCallbackQuery();
  try {
    switch (target) {
      case "tasks": {
        const tasks = await api.listTasks();
        await ctx.editMessageText(formatTasks(tasks), { parse_mode: "HTML" });
        break;
      }
      case "habits": {
        const habits = await api.listHabits();
        await ctx.editMessageText(formatHabits(habits), { parse_mode: "HTML" });
        break;
      }
      case "goals": {
        const goals = await api.listGoals();
        await ctx.editMessageText(formatGoals(goals), { parse_mode: "HTML" });
        break;
      }
      case "calendar": {
        const events = await api.getCalendarEvents();
        await ctx.editMessageText(formatCalendar(events), { parse_mode: "HTML" });
        break;
      }
    }
  } catch {
    await ctx.editMessageText("❌ Failed to load data.");
  }
});

// Catch-all for unknown callbacks
callbackHandlers.on("callback_query:data", async (ctx) => {
  await ctx.answerCallbackQuery();
});
