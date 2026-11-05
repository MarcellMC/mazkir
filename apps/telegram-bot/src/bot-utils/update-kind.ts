import type { Context } from "grammy";

/** The `kind` label on every update's log line and `telegram.update` span.
 *
 *  `live_location` covers both the message that starts a live share and each
 *  edit that moves it; before the location spike both were logged as a plain
 *  `location` or as `other`. */
export function updateKind(ctx: Pick<Context, "message" | "editedMessage" | "callbackQuery">): string {
  const message = ctx.message;
  if (message?.text) return "text";
  if (message?.photo) return "photo";
  if (ctx.editedMessage?.location || message?.location?.live_period !== undefined) return "live_location";
  if (message?.location) return "location";
  if (ctx.callbackQuery) return "callback";
  return "other";
}
