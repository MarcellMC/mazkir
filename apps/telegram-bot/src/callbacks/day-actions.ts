import { Composer } from "grammy";
import { api } from "../api/client.js";
import { buildDayRich } from "../formatters/day-rich.js";
import { buildBlockEditRich } from "../formatters/block-edit-rich.js";
import { editRich } from "../bot-utils/send-rich.js";
import { buildNavKeyboard } from "../keyboards/nav.js";
import { markActiveSpanError } from "../tracing-utils.js";
import { logger } from "../logger.js";
import { setSelectedDate, noteDayView } from "../state/selected-date.js";

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
  const data = await api.getDaily(date);
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
  await ctx.answerCallbackQuery({ text });
}

// MUST precede the `day:(.+)` date handler in callbacks/index.ts, or
// "refresh:2026-09-10" is parsed as a date.
dayActionHandlers.callbackQuery(/^day:refresh:(.+)$/, async (ctx) => {
  const date = ctx.match[1]!;
  await ctx.answerCallbackQuery({ text: "Refreshed" });
  try {
    await rerender(ctx, date);
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
  // Writes nothing, deliberately. A refused proposal reappears on the next
  // open (spec §4.3) rather than leaving behind a row whose only purpose is
  // suppression. If this ever starts writing, that decision was reversed
  // without anyone saying so — the test asserts the silence.
  await ctx.answerCallbackQuery({ text: "Skipped — it'll ask again" });
  try {
    await rerender(ctx, date);
  } catch (err) {
    await toastFailure(ctx, err, "Skip");
  }
});

dayActionHandlers.callbackQuery(/^prop:edit:([^:]+):(\d+):(\d+)$/, async (ctx) => {
  const date = ctx.match[1]!;
  const [start, end] = [Number(ctx.match[2]), Number(ctx.match[3])];
  await ctx.answerCallbackQuery();
  // A proposal has no block to edit yet, so there is nothing for the nudge pad
  // to operate on. Asking is the honest fallback, and the answer goes through
  // create_event like any other described block.
  await ctx.reply(
    `${hhmm(start)}–${hhmm(end)} on ${date} — tell me what it was and when.`,
  );
});

dayActionHandlers.callbackQuery(/^gap:fill:([^:]+):(\d+):(\d+)$/, async (ctx) => {
  const date = ctx.match[1]!;
  const [start, end] = [Number(ctx.match[2]), Number(ctx.match[3])];
  await ctx.answerCallbackQuery();
  // No proposal to accept, so ask. The answer goes through the normal NL path
  // into create_event, which Ship 4 already built.
  await ctx.reply(
    `${hhmm(start)}–${hhmm(end)} on ${date} — what was that? Just tell me.`,
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
  await ctx.answerCallbackQuery();
  try {
    const data = await api.getDaily(date);
    const block = data.blocks.find((b) => b.id === eventId);
    if (!block) {
      await ctx.answerCallbackQuery({ text: "That block is gone — refresh." });
      return;
    }
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
