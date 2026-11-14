import { Composer } from "grammy";
import { api, ApiError } from "../api/client.js";
import { buildReceiptRich } from "../formatters/receipt-rich.js";
import { editRich } from "../bot-utils/send-rich.js";
import { markActiveSpanError } from "../tracing-utils.js";
import { logger } from "../logger.js";
import { takeOpenQuestion, noteOpenQuestion } from "../state/open-question.js";

/** Taps on a trip message (location trips spec §6.2, §6.3).
 *
 *  `trip:<trip>:<line>:<action>`: the line is a stop (`s1`), `trip` for a
 *  question about the whole trip, an arrival line number, or `all`; the
 *  action is an option (`a0`–`a2`), `p` just a pause, `t` type it, `l` later (ask at home), `ok`, `no`.
 *  The server does the work and returns the redrawn message; ✎ is the day
 *  view's own `block:edit:…`. */
export const TRIP_TAP = /^trip:([0-9a-f]{8}):([a-z0-9]{1,6}):(ok|no|p|t|l|a[0-2])$/;

const GONE = "That trip is gone.";
const FAILED = "❌ That didn't work.";

export const tripHandlers = new Composer();

tripHandlers.callbackQuery(TRIP_TAP, async (ctx) => {
  const [, tripId, line, action] = ctx.match! as unknown as [string, string, string, string];
  let result;
  try {
    result = await api.tripTap(tripId, line, action);
  } catch (err) {
    markActiveSpanError(err);
    const gone = err instanceof ApiError && err.status === 404;
    logger.warn({ event_type: "trip_tap_failed", action, gone, err: String(err) }, "trip_tap_failed");
    try {
      await ctx.answerCallbackQuery({ text: gone ? GONE : FAILED });
    } catch {
      // already answered; the original failure is the one that matters
    }
    return;
  }

  try {
    await ctx.answerCallbackQuery(result.toast ? { text: result.toast } : undefined);
  } catch (err) {
    logger.warn({ event_type: "trip_tap_answer_failed", err: String(err) }, "trip_tap_answer_failed");
  }

  // The redraw is an edit, and every edit clears the open question
  // (bot.ts, dropPerMessageHints): whatever was pending is put back after.
  const chatId = ctx.chat?.id;
  const pending = chatId !== undefined ? takeOpenQuestion(chatId) : undefined;
  try {
    if (result.receipt) await editRich(ctx, buildReceiptRich(result.receipt));
  } catch (err) {
    markActiveSpanError(err);
    logger.warn({ event_type: "trip_redraw_failed", action, err: String(err) }, "trip_redraw_failed");
  } finally {
    if (chatId !== undefined) {
      // "✎ Something else" asks for your next message as the answer.
      const question = result.open_question ?? pending;
      if (question !== undefined && question !== null) noteOpenQuestion(chatId, question);
    }
  }
});
