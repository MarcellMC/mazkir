import { Composer } from "grammy";
import { api, ApiError } from "../api/client.js";
import { buildReceiptRich } from "../formatters/receipt-rich.js";
import { editRich } from "../bot-utils/send-rich.js";
import { markActiveSpanError } from "../tracing-utils.js";
import { logger } from "../logger.js";
import { takeOpenQuestion, noteOpenQuestion } from "../state/open-question.js";

/** Taps on a fast-lane receipt (spec §8.2). The server does the work and
 *  sends back the whole receipt, which replaces this one in place.
 *
 *  The pattern is the server's own (routes/fast_lane.py): a line number with
 *  a line action, or the turn's `u` line with `un`. Anything else is not a
 *  tap the server could answer, so it is left to the catch-all rather than
 *  sent. ✎ is `block:edit:…`, which the day view already handles. */
export const RECEIPT_TAP = /^rcpt:(t[0-9a-f]{8}):(?:([0-9]{1,4}):(ok|no|pl|hb|sy|sn)|(u):(un))$/;

const GONE = "That receipt is gone — receipts are kept for a day.";
const FAILED = "❌ That didn't work.";

export const receiptHandlers = new Composer();

receiptHandlers.callbackQuery(RECEIPT_TAP, async (ctx) => {
  const m = ctx.match!;
  const turnId = m[1]!;
  const line = (m[2] ?? m[4])!;
  const action = (m[3] ?? m[5])!;

  let result;
  try {
    result = await api.receiptAction(turnId, line, action);
  } catch (err) {
    markActiveSpanError(err);
    const gone = err instanceof ApiError && err.status === 404;
    logger.warn({ event_type: "receipt_tap_failed", action, gone, err: String(err) }, "receipt_tap_failed");
    try {
      await ctx.answerCallbackQuery({ text: gone ? GONE : FAILED });
    } catch {
      // already answered; the original failure is the one that matters
    }
    return;
  }

  // The server has acted: say so first, so a redraw Telegram refuses cannot
  // turn a tap that worked into one reported as failed.
  try {
    await ctx.answerCallbackQuery(result.toast ? { text: result.toast } : undefined);
  } catch (err) {
    logger.warn({ event_type: "receipt_tap_answer_failed", err: String(err) }, "receipt_tap_answer_failed");
  }

  // The redraw is an edit, and every edit clears the open question
  // (bot.ts, dropPerMessageHints). A tap answers a line, not the question
  // the receipt is still asking, so whatever was pending is put back. It is
  // only restored, never armed from the redrawn receipt: a tap on an old
  // receipt must not attach its question to the next, unrelated message.
  const chatId = ctx.chat?.id;
  const pending = chatId !== undefined ? takeOpenQuestion(chatId) : undefined;
  try {
    await editRich(ctx, buildReceiptRich(result.receipt));
  } catch (err) {
    markActiveSpanError(err);
    logger.warn({ event_type: "receipt_redraw_failed", action, err: String(err) }, "receipt_redraw_failed");
  } finally {
    if (chatId !== undefined && pending !== undefined) noteOpenQuestion(chatId, pending);
  }
});
