import { Composer } from "grammy";
import { api } from "../api/client.js";
import { formatCalendar } from "../formatters/telegram.js";
import { buildTasksRich, buildTaskDetailRich } from "../formatters/tasks-rich.js";
import { buildHabitsRich } from "../formatters/habits-rich.js";
import { buildGoalsRich, buildGoalDetailRich } from "../formatters/goals-rich.js";
import { markActiveSpanError } from "../tracing-utils.js";
import { sendRich, editRich } from "../bot-utils/send-rich.js";
import { buildDayRich } from "../formatters/day-rich.js";
import { buildNavKeyboard } from "../keyboards/nav.js";
import { logger } from "../logger.js";
import {
  setPendingConfirmation,
  clearPendingConfirmation,
} from "../state/pending-confirmations.js";
import { setSelectedDate, noteDayView } from "../state/selected-date.js";
import { stripSuppressedProposals } from "../state/dismissed-proposals.js";
import { dayActionHandlers } from "./day-actions.js";
import type { HabitCompletion } from "@mazkir/shared-types";

export const callbackHandlers = new Composer();

/** Toast text for a habit completion, reporting what it actually paid.
 *
 * `tokens_earned` is read with `?? 0` rather than checked for truthiness: a
 * habit configured with `tokens_per_completion: 0` did complete, and saying so
 * without a token clause is right. `already_completed` is the server's word for
 * "the day's target was already met", which is not a failure and not an award.
 */
function completionToast(name: string, result: HabitCompletion): string {
  if (result.already_completed) {
    return `Already done today — ${name} (${result.completions_today}/${result.daily_target})`;
  }
  const tokens = result.tokens_earned ?? 0;
  const parts = [`✅ ${name}`];
  if (tokens > 0) parts.push(`+${tokens} tokens`);
  if (result.new_streak !== undefined) parts.push(`streak ${result.new_streak}`);
  return parts.join(" · ");
}

// Registered before the `day:(.+)` date handler below: that pattern would
// otherwise swallow `day:refresh:2026-09-10` and `day:approveall:2026-09-10`
// and try to parse the whole tail as a date.
callbackHandlers.use(dayActionHandlers);

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
    const result = await api.completeHabit(name);
    // Say what it paid, as /day's approval toast does. This used to discard the
    // response and always answer "✅ completed!", so a repeat tap — which
    // writes nothing and awards nothing — was indistinguishable from a real
    // completion, and a genuine award was never visible as one. That is half of
    // "manually recording didn't trigger a token award"; the other half was the
    // award actually being lost server-side.
    await ctx.answerCallbackQuery({ text: completionToast(name, result) });
    // Refresh the habits list in-place. The re-render MUST carry
    // reply_markup: this edit used to omit it entirely, which stripped every
    // button from the message and left the user re-issuing /habits to get
    // them back.
    const habits = await api.listHabits();
    await editRich(ctx, buildHabitsRich(habits), {
      reply_markup: buildNavKeyboard("habits"),
    });
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
    await editRich(ctx, buildGoalDetailRich(detail), {
      reply_markup: buildNavKeyboard("goals"),
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
    const fresh = await api.getDaily(date);
    // Same suppression as day-actions' rerender: a proposal the user waved
    // away must not come back just because they stepped to another day and
    // back within the same sitting.
    const data = stripSuppressedProposals(ctx.chat!.id, fresh);
    setSelectedDate(ctx.chat!.id, data.date);
    await editRich(ctx, buildDayRich(data), { reply_markup: buildNavKeyboard("day") });
    noteDayView(ctx.chat!.id);
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
        await editRich(ctx, buildHabitsRich(habits), {
          reply_markup: buildNavKeyboard("habits"),
        });
        break;
      }
      case "goals": {
        const goals = await api.listGoals();
        await editRich(ctx, buildGoalsRich(goals), {
          reply_markup: buildNavKeyboard("goals"),
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
