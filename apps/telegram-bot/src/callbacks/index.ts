import { Composer } from "grammy";
import { api } from "../api/client.js";
import {
  formatHabits,
  formatCalendar,
  formatGoals,
  formatGoalDetail,
} from "../formatters/telegram.js";
import { buildTasksRich, buildTaskDetailRich } from "../formatters/tasks-rich.js";
import { buildGoalsKeyboard, buildGoalDetailKeyboard } from "../keyboards/goals.js";
import { buildHabitsKeyboard } from "../keyboards/habits.js";
import { markActiveSpanError } from "../tracing-utils.js";
import { sendRich, editRich } from "../bot-utils/send-rich.js";
import { buildDayRich } from "../formatters/day-rich.js";
import { buildNavKeyboard } from "../keyboards/nav.js";
import { logger } from "../logger.js";
import {
  setPendingConfirmation,
  clearPendingConfirmation,
} from "../state/pending-confirmations.js";

export const callbackHandlers = new Composer();

// Confirmation choice buttons. The action id comes from the callback data
// rather than module state, so a button on an older message cannot answer
// a newer confirmation.
callbackHandlers.callbackQuery(/^confirm:([^:]+):(.+)$/, async (ctx) => {
  const actionId = ctx.match[1]!;
  const value = ctx.match[2]!;
  try {
    await ctx.answerCallbackQuery();
    const chatId = ctx.chat?.id;
    if (!chatId) return;
    // Clear before sending: the server consumes the PendingAction on this
    // call, so leaving the entry behind would make the text handler treat
    // the user's NEXT message as a reply to an action that no longer
    // exists -- surfacing as "No pending action found" and swallowing
    // whatever they actually typed.
    clearPendingConfirmation(chatId);
    const response = await api.sendConfirmation(chatId, actionId, value);
    if (response.awaiting_confirmation && response.pending_action_id) {
      setPendingConfirmation(chatId, response.pending_action_id);
    }
    // The agent emits markdown, so this goes through sendRich like every
    // other agent reply. Sent as parse_mode HTML it rendered tables and
    // backticks as raw punctuation.
    await sendRich(ctx, { markdown: response.response });
  } catch (err) {
    markActiveSpanError(err);
    await ctx.reply("❌ Something went wrong answering that.");
  }
});

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
    await editRich(ctx, buildTaskDetailRich(detail), {
      reply_markup: buildNavKeyboard("tasks"),
    });
  } catch (err) {
    markActiveSpanError(err);
    await ctx.answerCallbackQuery({ text: "❌ Failed to load task" });
  }
});

// Goal detail view — tapping a goal in the list shows its full data.
// Goals have no completion endpoint, so the detail view is read-only.
callbackHandlers.callbackQuery(/^goal:view:(.+)$/, async (ctx) => {
  const slug = ctx.match[1]!;
  try {
    const detail = await api.getGoal(slug);
    await ctx.answerCallbackQuery();
    await ctx.editMessageText(formatGoalDetail(detail), {
      parse_mode: "HTML",
      reply_markup: buildGoalDetailKeyboard(),
    });
  } catch (err) {
    markActiveSpanError(err);
    await ctx.answerCallbackQuery({ text: "❌ Failed to load goal" });
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
    await editRich(ctx, buildTasksRich(tasks), {
      reply_markup: buildNavKeyboard("tasks"),
    });
  } catch (err) {
    markActiveSpanError(err);
    await ctx.answerCallbackQuery({ text: "❌ Failed to complete task" });
  }
});

// Date navigation re-renders the same message. The selected date lives in
// the callback data rather than server state, so a button on an old message
// still resolves to the day it was drawn for.
callbackHandlers.callbackQuery(/^day:(.+)$/, async (ctx) => {
  const arg = ctx.match[1]!;
  await ctx.answerCallbackQuery();
  const date = arg === "today" ? undefined : arg;
  try {
    const data = await api.getDaily(date);
    await editRich(ctx, buildDayRich(data), { reply_markup: buildNavKeyboard("day") });
  } catch (err) {
    markActiveSpanError(err);
    // The error report is itself an edit and can itself be rejected (e.g.
    // chained from the same "not modified" condition, or a second identical
    // failure). `bot.catch()` (bot.ts) would still net this, but logging
    // and giving up quietly here avoids bouncing it through the bot-wide
    // boundary — the user still has the previous message on screen.
    try {
      await ctx.editMessageText("❌ Failed to load the day.");
    } catch (reportErr) {
      logger.warn(
        { event_type: "day_error_report_failed", err: String(reportErr) },
        "day_error_report_failed",
      );
    }
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
        await editRich(ctx, buildTasksRich(tasks), {
          reply_markup: buildNavKeyboard("tasks"),
        });
        break;
      }
      case "habits": {
        const habits = await api.listHabits();
        await ctx.editMessageText(formatHabits(habits), {
          parse_mode: "HTML",
          reply_markup: buildHabitsKeyboard(habits),
        });
        break;
      }
      case "goals": {
        const goals = await api.listGoals();
        await ctx.editMessageText(formatGoals(goals), {
          parse_mode: "HTML",
          reply_markup: buildGoalsKeyboard(goals),
        });
        break;
      }
      case "calendar": {
        const events = await api.getCalendarEvents();
        await ctx.editMessageText(formatCalendar(events), { parse_mode: "HTML" });
        break;
      }
      case "day": {
        const data = await api.getDaily();
        await editRich(ctx, buildDayRich(data), { reply_markup: buildNavKeyboard("day") });
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
