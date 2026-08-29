import type { Context, InputFile } from "grammy";
import type { InputRichMessage } from "@grammyjs/types";
import { markActiveSpanError } from "../tracing-utils.js";
import { logger } from "../logger.js";

// Rich content is an extended markup string in InputRichMessage. Send via
// ctx.replyWithRichMessage, edit via editMessageText's `rich_message`
// parameter — added in Bot API 10.1, the same release that introduced rich
// messages. An earlier comment here claimed rich was send-once; it never was.

/** Best-effort plain text for the catch-all fallback: strip tags + decode the
 *  few entities our formatters emit. Never throws. */
export function richToPlainText(msg: InputRichMessage<InputFile>): string {
  const raw = msg.html ?? msg.markdown ?? "";
  return raw
    .replace(/<[^>]+>/g, " ")   // tags become a space so adjacent words don't merge
    .replaceAll("&amp;", "&")
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replace(/\s+/g, " ")
    .trim();
}

/** Send a rich message; fall back to plain text if the payload is rejected or
 *  oversized. A bad rich payload must never drop the message. `extra` carries
 *  reply_markup etc. */
export async function sendRich(
  ctx: Context,
  msg: InputRichMessage<InputFile>,
  extra?: Record<string, unknown>,
): Promise<void> {
  try {
    await ctx.replyWithRichMessage(msg, extra as never);
  } catch (err) {
    markActiveSpanError(err);
    // Log the cause: a silent downgrade made a missing env var
    // undiagnosable when this last fired.
    logger.warn(
      { event_type: "rich_message_fallback", err: String(err) },
      "rich_message_fallback",
    );
    // `extra` carries reply_markup. Dropping it strips an inline keyboard
    // from the fallback, leaving a prompt the user cannot answer.
    await ctx.reply(richToPlainText(msg), extra as never);
  }
}

/** True when a Telegram API rejection is the harmless "message is not
 *  modified" error — the edit asked for exactly the content already on
 *  screen (e.g. re-tapping the highlighted day in the week bar, or `today`
 *  while already viewing today). `GrammyError` carries this in
 *  `description`; fall back to `message` for anything else that merely
 *  looks like one, since `Error`'s own message text embeds the same
 *  description grammY reports. */
function isNotModifiedError(err: unknown): boolean {
  if (!(err instanceof Error)) return false;
  const text = (err as { description?: unknown }).description;
  const haystack = typeof text === "string" ? text : err.message;
  return /message is not modified/i.test(haystack);
}

/** Edit a message in place with rich content, falling back to plain text if
 *  the payload is rejected. The sibling of sendRich: navigation re-renders
 *  the same message, so a rejected payload must degrade rather than leave
 *  the user staring at a stale day.
 *
 *  One rejection is not a bad payload, though: re-tapping the day already
 *  on screen sends byte-identical content, and Telegram answers that with
 *  "message is not modified". Routing that through the fallback would
 *  succeed (the plain text differs from the rich HTML) and silently strip
 *  the in-body `<tg-button-row>` navigation — the message's only way to
 *  navigate, since it isn't in `reply_markup`. The message already shows
 *  what we wanted; treat it as a no-op, not a failure. */
export async function editRich(
  ctx: Context,
  msg: InputRichMessage<InputFile>,
): Promise<void> {
  try {
    await ctx.editMessageText(msg);
  } catch (err) {
    if (isNotModifiedError(err)) return;
    markActiveSpanError(err);
    logger.warn(
      { event_type: "rich_edit_fallback", err: String(err) },
      "rich_edit_fallback",
    );
    await ctx.editMessageText(richToPlainText(msg));
  }
}
