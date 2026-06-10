import { Composer } from "grammy";
import { api } from "../api/client.js";
import {
  formatTasks,
  formatTaskDetail,
  formatHabits,
  formatCalendar,
  formatGoals,
} from "../formatters/telegram.js";
import { buildTasksKeyboard, buildTaskDetailKeyboard } from "../keyboards/tasks.js";
import { markActiveSpanError } from "../tracing-utils.js";

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
  } catch (err) {
    markActiveSpanError(err);
    await ctx.answerCallbackQuery({ text: "❌ Failed to complete habit" });
  }
});

// Task detail view — tapping a task in the list shows its full data
// with a Complete button.
callbackHandlers.callbackQuery(/^task:view:(.+)$/, async (ctx) => {
  const slug = ctx.match[1]!;
  try {
    const detail = await api.getTask(slug);
    await ctx.answerCallbackQuery();
    await ctx.editMessageText(formatTaskDetail(detail), {
      parse_mode: "HTML",
      reply_markup: buildTaskDetailKeyboard(detail.slug),
    });
  } catch (err) {
    markActiveSpanError(err);
    await ctx.answerCallbackQuery({ text: "❌ Failed to load task" });
  }
});

// Task completion. `task:done:` carries a slug (from the detail view);
// legacy `task:complete:` buttons carry a name — the server resolves both.
callbackHandlers.callbackQuery(/^task:(?:done|complete):(.+)$/, async (ctx) => {
  const ref = ctx.match[1]!;
  try {
    await api.completeTask(ref);
    await ctx.answerCallbackQuery({ text: "✅ Task completed!" });
    const tasks = await api.listTasks();
    await ctx.editMessageText(formatTasks(tasks), {
      parse_mode: "HTML",
      reply_markup: buildTasksKeyboard(tasks),
    });
  } catch (err) {
    markActiveSpanError(err);
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
        await ctx.editMessageText(formatTasks(tasks), {
          parse_mode: "HTML",
          reply_markup: buildTasksKeyboard(tasks),
        });
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
  } catch (err) {
    markActiveSpanError(err);
    await ctx.editMessageText("❌ Failed to load data.");
  }
});

// Catch-all for unknown callbacks
callbackHandlers.on("callback_query:data", async (ctx) => {
  await ctx.answerCallbackQuery();
});
