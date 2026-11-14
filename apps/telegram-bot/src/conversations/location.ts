/**
 * Live location and check-ins → POST /locations/points (location spike L0,
 * docs/specs/2026-11-05-location-check-in-design.md §4.2).
 *
 * Registered before `messageHandler`, which also listens to
 * `message:location`:
 *  - an edited live location (each new position) is posted and stops here;
 *  - the message that starts a live share is posted and stops here — it used
 *    to start an agent turn about a bare location, which helped nobody;
 *  - a one-off location or venue is a check-in: posted, then passed on to
 *    the agent exactly as before.
 *  - a forwarded location is never a check-in: it passes straight on.
 * With LOCATION_INGEST off, every update passes straight through.
 *
 * A failed post is logged and dropped; it never stops a check-in reaching
 * the agent. The log line carries no coordinates.
 *
 * Location trips (docs/specs/2026-11-10-location-trips-design.md §6.1): with
 * LOCATION_AWARENESS on at the server, the response carries `notify[]` —
 * questions about a stop, the message when you are back, notices. Each is
 * sent here as a rich message and then acknowledged; one that fails to send
 * is not acknowledged, so the next point's response carries it again.
 */
import { Composer, type Context } from "grammy";
import type { Message } from "grammy/types";
import { api, ApiError, type LocationPoint } from "../api/client.js";
import type { LocationNotify } from "@mazkir/shared-types";
import { sendRich } from "../bot-utils/send-rich.js";
import { buildReceiptRich } from "../formatters/receipt-rich.js";
import { noteOpenQuestion } from "../state/open-question.js";
import { config } from "../config.js";
import { logger } from "../logger.js";

export function toLocationPoint(msg: Message, kind: LocationPoint["kind"]): LocationPoint {
  const loc = msg.location ?? msg.venue?.location;
  if (!loc) throw new Error("toLocationPoint: message carries no location");
  const seconds = kind === "live" ? (msg.edit_date ?? msg.date) : msg.date;
  const point: LocationPoint = {
    source: "telegram",
    kind,
    message_id: msg.message_id,
    ts: new Date(seconds * 1000).toISOString(),
    lat: loc.latitude,
    lng: loc.longitude,
  };
  if (loc.horizontal_accuracy !== undefined) point.accuracy_m = loc.horizontal_accuracy;
  if (loc.heading !== undefined) point.heading = loc.heading;
  if (loc.live_period !== undefined) point.live_period = loc.live_period;
  if (msg.venue?.title !== undefined) point.venue_title = msg.venue.title;
  return point;
}

async function ingest(ctx: Context, point: LocationPoint): Promise<void> {
  const chatId = ctx.chat?.id;
  if (chatId !== undefined) point.chat_id = chatId;
  let notify: LocationNotify[] = [];
  try {
    notify = (await api.postLocationPoint(point))?.notify ?? [];
  } catch (err) {
    logger.warn(
      {
        event_type: "location_ingest_failed",
        kind: point.kind,
        status: err instanceof ApiError ? err.status : "error",
        err: String(err),
      },
      "location_ingest_failed",
    );
    return;
  }
  for (const item of notify) await deliver(ctx, item);
}

/** Send one trip message, then acknowledge it. The open question is armed
 *  after the send: every send clears it (bot.ts, dropPerMessageHints). */
async function deliver(ctx: Context, item: LocationNotify): Promise<void> {
  try {
    await sendRich(ctx, buildReceiptRich(item.receipt));
  } catch (err) {
    logger.warn({ event_type: "location_notify_failed", kind: item.kind, err: String(err) }, "location_notify_failed");
    return;
  }
  const chatId = ctx.chat?.id;
  if (item.receipt.open_question && chatId !== undefined) noteOpenQuestion(chatId, item.receipt.open_question);
  try {
    await api.ackLocationOutbox(item.id);
  } catch (err) {
    logger.warn({ event_type: "location_notify_ack_failed", kind: item.kind, err: String(err) }, "location_notify_ack_failed");
  }
}

export const locationHandler = new Composer<Context>();

locationHandler.on("edited_message:location", async (ctx, next) => {
  if (!config.locationIngest) return next();
  await ingest(ctx, toLocationPoint(ctx.editedMessage, "live"));
});

locationHandler.on("message:location", async (ctx, next) => {
  if (!config.locationIngest) return next();
  const msg = ctx.message;
  // A forwarded location or venue is somebody else's place, not where you
  // are: it goes to the agent as forwarded context, as every forward does.
  if (msg.forward_origin) return next();
  if (msg.location.live_period !== undefined) {
    await ingest(ctx, toLocationPoint(msg, "live_start"));
    return;
  }
  await ingest(ctx, toLocationPoint(msg, "check_in"));
  await next();
});
