import type { Context, InputFile } from "grammy";
import type { InputRichMessage } from "@grammyjs/types";
import { markActiveSpanError } from "../tracing-utils.js";
import { logger } from "../logger.js";

// Rich content is an extended markup string in InputRichMessage. Send via the
// grammY context method ctx.replyWithRichMessage. There is no editMessageText on
// the rich path — rich is send-once only.

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
