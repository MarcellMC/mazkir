import { Composer } from "grammy";
import { api } from "../api/client.js";
import { buildDayRich } from "../formatters/day-rich.js";
import { buildBlockEditRich } from "../formatters/block-edit-rich.js";
import { editRich } from "../bot-utils/send-rich.js";
import { buildNavKeyboard } from "../keyboards/nav.js";
import { markActiveSpanError } from "../tracing-utils.js";
import { logger } from "../logger.js";
import { setSelectedDate, noteDayView } from "../state/selected-date.js";
import {
  suppressProposal,
  stripSuppressedProposals,
} from "../state/dismissed-proposals.js";

export const dayActionHandlers = new Composer();

/** "HH:MM" from minutes since midnight — the inverse of day-rich's toMinutes.
 *  Callback data carries minutes because they are compact and unambiguous. */
export function hhmm(minutes: number): string {
  const m = Math.max(0, Math.floor(minutes));
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

/** Re-render the day in place. Every action ends here, because the day view IS
 *  the feedback — a toast alone leaves stale glyphs and stale numbers on
 *  screen. */
async function rerender(ctx: any, date: string): Promise<void> {
  const fresh = await api.getDaily(date);
  // Drop the proposals this chat has waved away. Without this, ✕ recomputes
  // and redraws the very row it just dismissed (spec §4.3 writes nothing by
  // design), so the tap read as broken.
  const data = stripSuppressedProposals(ctx.chat!.id, fresh);
  setSelectedDate(ctx.chat!.id, data.date);
  await editRich(ctx, buildDayRich(data), { reply_markup: buildNavKeyboard("day") });
  noteDayView(ctx.chat!.id);
}

/** Report a failure as a toast and leave the message alone. The previous
 *  render is still navigable; replacing it with an error string would cost the
 *  user their whole day view to tell them one tap failed. */
async function toastFailure(ctx: any, err: unknown, what: string): Promise<void> {
  markActiveSpanError(err);
  logger.warn(
    { event_type: "day_action_failed", what, err: String(err) },
    "day_action_failed",
  );
  const text = String(err).includes("409")
    ? "Can't undo that here — untick it in /habits."
    : `❌ ${what} failed.`;
  // A handler may already have answered before failing, and Telegram rejects a
  // second answer to the same query. Swallow that rejection: the original
  // failure is the one worth reporting, and letting this throw from inside a
  // catch block would replace it with a less useful error.
  try {
    await ctx.answerCallbackQuery({ text });
  } catch (answerErr) {
    logger.warn(
      { event_type: "day_action_toast_failed", what, err: String(answerErr) },
      "day_action_toast_failed",
    );
  }
}

// MUST precede the `day:(.+)` date handler in callbacks/index.ts, or
// "refresh:2026-09-10" is parsed as a date.
dayActionHandlers.callbackQuery(/^day:refresh:(.+)$/, async (ctx) => {
  const date = ctx.match[1]!;
  try {
    await rerender(ctx, date);
    // After, not before: this used to report "Refreshed" and then fail, which
    // told the user the opposite of what happened.
    await ctx.answerCallbackQuery({ text: "Refreshed" });
  } catch (err) {
    await toastFailure(ctx, err, "Refresh");
  }
});

dayActionHandlers.callbackQuery(/^day:approveall:(.+)$/, async (ctx) => {
  const date = ctx.match[1]!;
  try {
    const result = await api.approveAll(date);
    const guesses = result.approved.filter((a) => a.was_guess);
    // Name the guesses. approve-all banks them (spec §5.6), so a wrong sleep
    // block has to be visible in the same breath rather than discovered weeks
    // later in the readout.
    let text = `✓ Approved ${result.approved.length}`;
    if (guesses.length > 0) {
      text += `, including ${guesses.map((g) => g.name).join(", ")} (a guess)`;
    }
    if (result.failed.length > 0) {
      text += ` · ${result.failed.length} could not be approved`;
    }
    await ctx.answerCallbackQuery({ text });
    await rerender(ctx, date);
  } catch (err) {
    await toastFailure(ctx, err, "Approve all");
  }
});

dayActionHandlers.callbackQuery(/^block:(approve|dismiss):([^:]+):(.+)$/, async (ctx) => {
  const action = ctx.match[1] as "approve" | "dismiss";
  const date = ctx.match[2]!;
  const eventId = ctx.match[3]!;
  const state = action === "approve" ? "approved" : "dismissed";
  try {
    const result = await api.setBlockState(date, eventId, state);
    // Say what it paid. A silent token award is one the user never connects
    // to the tap that earned it, which defeats the point of paying.
    const text = result.habit
      ? `✓ ${result.habit.name} · +${result.habit.tokens_earned} tokens · streak ${result.habit.new_streak}`
      : action === "approve" ? "✓ Confirmed" : "Dismissed";
    await ctx.answerCallbackQuery({ text });
    await rerender(ctx, date);
  } catch (err) {
    await toastFailure(ctx, err, action === "approve" ? "Confirm" : "Dismiss");
  }
});

dayActionHandlers.callbackQuery(/^prop:approve:([^:]+):(\d+):(\d+)$/, async (ctx) => {
  const date = ctx.match[1]!;
  const [start, end] = [Number(ctx.match[2]), Number(ctx.match[3])];
  try {
    // No name: the server recomputes the proposal for this interval (§4.2).
    // A client-sent name is a client-sent write, and a long one would not fit
    // in the 64 bytes Telegram allows.
    const result = await api.fillGap(date, hhmm(start), hhmm(end), undefined);
    await ctx.answerCallbackQuery({ text: `✓ ${result.name}` });
    await rerender(ctx, date);
  } catch (err) {
    await toastFailure(ctx, err, "Confirm");
  }
});

dayActionHandlers.callbackQuery(/^prop:dismiss:([^:]+):(\d+):(\d+)$/, async (ctx) => {
  const date = ctx.match[1]!;
  const [start, end] = [Number(ctx.match[2]), Number(ctx.match[3])];
  // Still writes nothing to the vault, deliberately (spec §4.3): no
  // tombstone, and the proposal is free to ask again later. What changed is
  // that the refusal is now remembered in memory for this chat, so the
  // re-render below does not immediately redraw the row it just dismissed.
  // If this ever starts writing to the server, that decision was reversed
  // without anyone saying so — the test asserts the silence.
  suppressProposal(ctx.chat!.id, date, hhmm(start), hhmm(end));
  await ctx.answerCallbackQuery({ text: "Skipped — it'll ask again later" });
  try {
    await rerender(ctx, date);
  } catch (err) {
    await toastFailure(ctx, err, "Skip");
  }
});

dayActionHandlers.callbackQuery(/^prop:edit:([^:]+):(\d+):(\d+)$/, async (ctx) => {
  const date = ctx.match[1]!;
  const [start, end] = [Number(ctx.match[2]), Number(ctx.match[3])];
  // A proposal has no block, and the nudge pad needs one to operate on — so
  // accept the guess first, then open the pad on the block that creates.
  // Tapping ✎ already means "yes, roughly this, let me fix it", so banking
  // the interval is not a decision taken on the user's behalf; walking away
  // leaves exactly what ✓ would have left.
  //
  // No name is sent: the server recomputes the proposal for the interval
  // (§4.2), so a client can never write a name of its choosing.
  try {
    const filled = await api.fillGap(date, hhmm(start), hhmm(end), undefined);
    const data = await api.getDaily(date);
    const block = data.blocks.find((b) => b.id === filled.event_id);
    if (!block) {
      // Created, but not drawable yet — report the truth rather than opening
      // an editor on nothing.
      await ctx.answerCallbackQuery({ text: `✓ ${filled.name} — refresh to edit` });
      await rerender(ctx, date);
      return;
    }
    await ctx.answerCallbackQuery();
    await editRich(ctx, buildBlockEditRich(block, date, 0, 0),
      { reply_markup: buildNavKeyboard("day") });
  } catch (err) {
    // 422 means the server had nothing to propose for this interval, which
    // is not a failure — there is simply no guess to adjust. Fall back to
    // asking, carrying both the interval and the fact that it is a gap so
    // one reply can finish it.
    if (String(err).includes("422")) {
      await ctx.answerCallbackQuery();
      await ctx.reply(
        `${hhmm(start)}–${hhmm(end)} on ${date} is unaccounted — what was it?`,
      );
      return;
    }
    await toastFailure(ctx, err, "Edit");
  }
});

dayActionHandlers.callbackQuery(/^gap:fill:([^:]+):(\d+):(\d+)$/, async (ctx) => {
  const date = ctx.match[1]!;
  const [start, end] = [Number(ctx.match[2]), Number(ctx.match[3])];
  await ctx.answerCallbackQuery();
  // No proposal to accept, so ask. The answer goes through the normal NL path
  // into create_event, which Ship 4 already built.
  //
  // The interval is stated as already known and the reply narrowed to the
  // activity, so one message finishes it. The old wording ("what was that?
  // Just tell me") invited a bare time range, and answering it with times
  // left the agent still needing the activity — a three-turn round trip for
  // one block, seen on 2026-09-12.
  await ctx.reply(
    `${hhmm(start)}–${hhmm(end)} on ${date} is unaccounted — what was it? ` +
      `Just the activity is enough, or say different times to change them.`,
  );
});

dayActionHandlers.callbackQuery(/^block:edit:([^:]+):(.+)$/, async (ctx) => {
  const date = ctx.match[1]!;
  const eventId = ctx.match[2]!;
  try {
    const data = await api.getDaily(date);
    const block = data.blocks.find((b) => b.id === eventId);
    if (!block) {
      await ctx.answerCallbackQuery({ text: "That block is gone — refresh." });
      return;
    }
    await ctx.answerCallbackQuery();
    await editRich(ctx, buildBlockEditRich(block, date, 0, 0),
      { reply_markup: buildNavKeyboard("day") });
  } catch (err) {
    await toastFailure(ctx, err, "Edit");
  }
});

/** "HH:MM" shifted by `delta` minutes, wrapping at midnight. */
function shiftClock(hhmmStr: string, delta: number): string {
  const [h, m] = hhmmStr.split(":").map(Number);
  return hhmm(((((h ?? 0) * 60 + (m ?? 0) + delta) % 1440) + 1440) % 1440);
}

dayActionHandlers.callbackQuery(/^adj:([^:]+):([^:]+):(-?\d+):(-?\d+)$/, async (ctx) => {
  const date = ctx.match[1]!;
  const eventId = ctx.match[2]!;
  const [startDelta, endDelta] = [Number(ctx.match[3]), Number(ctx.match[4])];
  try {
    const data = await api.getDaily(date);
    const block = data.blocks.find((b) => b.id === eventId);
    if (!block) {
      await ctx.answerCallbackQuery({ text: "That block is gone — refresh." });
      return;
    }
    await ctx.answerCallbackQuery();
    await editRich(ctx, buildBlockEditRich(block, date, startDelta, endDelta),
      { reply_markup: buildNavKeyboard("day") });
  } catch (err) {
    await toastFailure(ctx, err, "Adjust");
  }
});

dayActionHandlers.callbackQuery(/^adjsave:([^:]+):([^:]+):(-?\d+):(-?\d+)$/, async (ctx) => {
  const date = ctx.match[1]!;
  const eventId = ctx.match[2]!;
  const [startDelta, endDelta] = [Number(ctx.match[3]), Number(ctx.match[4])];
  try {
    const data = await api.getDaily(date);
    const block = data.blocks.find((b) => b.id === eventId);
    if (!block) {
      await ctx.answerCallbackQuery({ text: "That block is gone — refresh." });
      return;
    }
    if (startDelta !== 0 || endDelta !== 0) {
      // PATCH pins what it sets (Task 9), so these times survive the next
      // merge instead of being overwritten from the source.
      await api.patchEvent(date, eventId, {
        start_time: `${date}T${shiftClock(block.start, startDelta)}`,
        end_time: `${date}T${shiftClock(block.end, endDelta)}`,
      });
    }
    if (block.state === "pending") {
      await api.setBlockState(date, eventId, "approved");
    }
    await ctx.answerCallbackQuery({ text: "✓ Saved" });
    await rerender(ctx, date);
  } catch (err) {
    await toastFailure(ctx, err, "Save");
  }
});

dayActionHandlers.callbackQuery(/^cal:(cancel|delete):(.+)$/, async (ctx) => {
  // Deferred from this ship (spec §6.3, §9): the user chose local dismissal
  // for now, "cheap and non-destructive", pending real use to see which of the
  // two they reach for. The buttons are drawn because the layout was approved
  // with them; they say so rather than silently doing nothing.
  await ctx.answerCallbackQuery({
    text: "Not wired up yet — ✕ on the day view dismisses it locally.",
  });
});
