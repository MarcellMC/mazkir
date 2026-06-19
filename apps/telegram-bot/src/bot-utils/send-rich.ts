import type { Context } from "grammy";
import type { InputRichMessage } from "@grammyjs/types";
import { markActiveSpanError } from "../tracing-utils.js";

// Rich content is an extended markup string in InputRichMessage. Send via the
// grammY context method ctx.replyWithRichMessage. There is no editMessageText on
// the rich path — rich is send-once only.

/** Best-effort plain text for the catch-all fallback: strip tags + decode the
 *  few entities our formatters emit. Never throws. */
export function richToPlainText(msg: InputRichMessage): string {
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
  msg: InputRichMessage,
  extra?: Record<string, unknown>,
): Promise<void> {
  try {
    await ctx.replyWithRichMessage(msg, extra as never);
  } catch (err) {
    markActiveSpanError(err);
    await ctx.reply(richToPlainText(msg));
  }
}
