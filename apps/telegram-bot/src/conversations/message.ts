import { Composer, type Context } from "grammy";
import type { Message } from "grammy/types";
import type {
  Attachment,
  ReplyContext,
  ForwardContext,
  MessageResponse,
  Receipt,
} from "@mazkir/shared-types";
import { api, streamMessage } from "../api/client.js";
import { config } from "../config.js";
import {
  markActiveSpanError,
  setActiveSpanOutput,
  setPayloadProvenance,
  type ReplyToSource,
} from "../tracing-utils.js";
import { sendRich, isNotModifiedError } from "../bot-utils/send-rich.js";
import { buildReceiptRich } from "../formatters/receipt-rich.js";
import { logger } from "../logger.js";
import { repliedToText } from "../bot-utils/rich-text.js";
import { buildConfirmationKeyboard } from "../keyboards/confirmation.js";
import {
  getPendingConfirmation,
  setPendingConfirmation,
  clearPendingConfirmation,
} from "../state/pending-confirmations.js";
import { getSelectedDate } from "../state/selected-date.js";
import {
  takeOpenQuestion,
  clearOpenQuestion,
  noteOpenQuestion,
} from "../state/open-question.js";

/** Inline keyboard for a confirmation that names its options, or undefined
 *  for a plain yes/no gate (which is still answered as free text). The bot
 *  renders whatever the server names and knows nothing about what the
 *  pending tool does. */
function confirmExtra(response: {
  awaiting_confirmation?: boolean;
  pending_action_id?: string;
  confirmation_choices?: { value: string; label: string }[] | null;
}): { reply_markup: ReturnType<typeof buildConfirmationKeyboard> } | undefined {
  if (
    !response.awaiting_confirmation ||
    !response.pending_action_id ||
    !response.confirmation_choices?.length
  ) {
    return undefined;
  }
  return {
    reply_markup: buildConfirmationKeyboard(
      response.pending_action_id,
      response.confirmation_choices,
    ),
  };
}

/**
 * Build the enriched message payload from a Telegram message.
 * Exported for testing.
 */
export function buildMessagePayload(msg: Message, chatId: number) {
  // Text: prefer .text, fall back to .caption (for photo messages)
  const text = msg.text ?? msg.caption ?? "";

  // Attachments
  const attachments: Attachment[] = [];

  if (msg.location && !msg.venue) {
    attachments.push({
      type: "location",
      latitude: msg.location.latitude,
      longitude: msg.location.longitude,
    });
  }

  if (msg.venue) {
    attachments.push({
      type: "location",
      latitude: msg.venue.location.latitude,
      longitude: msg.venue.location.longitude,
      title: msg.venue.title,
    });
  }

  // Note: photo attachments handled separately (async download needed)
  // We just mark presence here; the handler adds the data after download.

  // Reply context
  let reply_to: ReplyContext | undefined;
  let replyToSource: ReplyToSource = "none";
  // Not `reply_to_message.text`: agent answers and the day/task/habit/goal
  // views are rich messages with no `.text`, so reading it dropped every
  // reply to them (2026-09-15, and silently since 2026-06-19).
  const answered = repliedToText(msg);
  if (msg.reply_to_message && answered) {
    reply_to = {
      text: answered,
      from: msg.reply_to_message.from?.is_bot ? "assistant" : "user",
    };
    replyToSource = "telegram";
    // An explicit reply answers whatever the user pointed at, so any question
    // the bot was still holding is no longer the thing being answered.
    clearOpenQuestion(chatId);
  } else {
    // No explicit reply, but the bot may have asked something one turn ago
    // that never reached the server — a gap prompt names an interval, and
    // answering it with just "Bar hopping" left the agent asking for times
    // the bot had already stated (2026-09-12 17:56). Present the question as
    // the reply-to the user did not have to make.
    const asked = takeOpenQuestion(chatId);
    if (asked) {
      reply_to = { text: asked, from: "assistant" };
      replyToSource = "open_question";
    }
  }

  // Forward context
  let forwarded_from: ForwardContext | undefined;
  if (msg.forward_origin) {
    const origin = msg.forward_origin;
    let from_name = "Unknown";
    if (origin.type === "user" && "sender_user" in origin) {
      from_name = (origin as any).sender_user.first_name ?? "Unknown";
    } else if (origin.type === "channel" && "chat" in origin) {
      from_name = (origin as any).chat.title ?? "Channel";
    } else if (origin.type === "hidden_user" && "sender_user_name" in origin) {
      from_name = (origin as any).sender_user_name ?? "Hidden User";
    }
    forwarded_from = {
      from_name,
      text,
      date: new Date(origin.date * 1000).toISOString(),
    };
  }

  const selected_date = getSelectedDate(chatId);

  // Stamped here rather than at the call site: this function is the only
  // place that knows whether the reply context was the user's own or the
  // bot's own question handed back, and that distinction is the diagnostic.
  setPayloadProvenance({
    replyToSource,
    selectedDate: selected_date,
    attachmentCount: attachments.length,
    hasForwardedFrom: forwarded_from !== undefined,
  });

  return {
    text,
    chat_id: chatId,
    // The server keys a fast-lane turn on it, so a redelivered or resent
    // message is answered from the first turn instead of writing again.
    ...(msg.message_id ? { message_id: msg.message_id } : {}),
    ...(selected_date ? { selected_date } : {}),
    ...(attachments.length > 0 ? { attachments } : {}),
    ...(reply_to ? { reply_to } : {}),
    ...(forwarded_from ? { forwarded_from } : {}),
  };
}

/**
 * Download a photo from Telegram and return base64-encoded bytes.
 */
async function downloadPhoto(
  fileId: string,
  botToken: string,
): Promise<{ data: string; mime_type: string } | null> {
  try {
    const fileRes = await fetch(
      `https://api.telegram.org/bot${botToken}/getFile?file_id=${fileId}`,
    );
    const fileJson = (await fileRes.json()) as {
      ok: boolean;
      result?: { file_path: string };
    };
    if (!fileJson.ok || !fileJson.result?.file_path) return null;

    const fileUrl = `https://api.telegram.org/file/bot${botToken}/${fileJson.result.file_path}`;
    const response = await fetch(fileUrl);
    if (!response.ok) return null;

    const buffer = await response.arrayBuffer();
    const base64 = Buffer.from(buffer).toString("base64");

    // Determine MIME type from file extension
    const ext = fileJson.result.file_path.split(".").pop()?.toLowerCase();
    const mime_type =
      ext === "png" ? "image/png" : ext === "webp" ? "image/webp" : "image/jpeg";

    return { data: base64, mime_type };
  } catch {
    return null;
  }
}

/** Send what the server answered: the receipt (unless streaming already sent
 *  it), then the reply, unless the fast lane's receipt already says it all.
 *  A fast turn with no receipt is one whose writes ran but whose receipt
 *  failed to render; its text says so and is sent, and the message is never
 *  sent to the agent again (that would write twice).
 *
 *  A question the receipt asks is held for the next message, armed last,
 *  because every send clears it (bot.ts, dropPerMessageHints). Exported for
 *  testing. */
export async function sendFinal(
  ctx: Context,
  chatId: number,
  response: MessageResponse,
  receiptSent: boolean,
): Promise<void> {
  if (response.receipt && !receiptSent) {
    await sendRich(ctx, buildReceiptRich(response.receipt));
  }
  const receiptSaysItAll = response.route === "fast" && Boolean(response.receipt);
  if (!receiptSaysItAll && response.response) {
    await sendRich(ctx, { markdown: response.response }, confirmExtra(response));
  }
  if (response.receipt?.open_question) {
    noteOpenQuestion(chatId, response.receipt.open_question);
  }
}

/** Redraw a sent receipt in place. Best-effort: a refused edit is logged and
 *  the turn goes on. "Not modified" (a duplicate update) is silent, and no
 *  failure falls back to plain text, which would strip the receipt's
 *  buttons. */
async function redrawReceipt(
  ctx: Context,
  chatId: number,
  messageId: number,
  receipt: Receipt,
): Promise<void> {
  try {
    await ctx.api.editMessageText(chatId, messageId, buildReceiptRich(receipt));
  } catch (err) {
    if (isNotModifiedError(err)) return;
    logger.warn({ event_type: "receipt_redraw_failed", err: String(err) }, "receipt_redraw_failed");
  }
}

export const messageHandler = new Composer();

/** Image MIME types Claude vision accepts — other documents are skipped. */
export const SUPPORTED_IMAGE_MIMES = new Set([
  "image/jpeg",
  "image/png",
  "image/webp",
  "image/gif",
]);

function timestampFilename(ext = "jpg"): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `photo_${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}_${pad(now.getHours())}-${pad(now.getMinutes())}-${pad(now.getSeconds())}.${ext}`;
}

// Handle text, photo, document (image files keep EXIF), and location messages
messageHandler.on(
  ["message:text", "message:photo", "message:document", "message:location"],
  async (ctx) => {
    const msg = ctx.message;
    const chatId = ctx.chat.id;
    const text = msg.text ?? msg.caption ?? "";

    // Skip commands (already handled)
    if (text.startsWith("/")) return;

    try {
      await ctx.replyWithChatAction("typing");

      // Check for pending confirmation (only for plain text replies)
      const pendingActionId = getPendingConfirmation(chatId);
      if (pendingActionId && msg.text && !msg.photo && !msg.location) {
        clearPendingConfirmation(chatId);
        const response = await api.sendConfirmation(
          chatId,
          pendingActionId,
          text,
        );
        if (response.awaiting_confirmation && response.pending_action_id) {
          setPendingConfirmation(chatId, response.pending_action_id);
        }
        setActiveSpanOutput(response.response);
        // Agent replies are markdown; same rendering path as every other
        // agent reply, and it carries any follow-on confirmation buttons.
        await sendRich(ctx, { markdown: response.response }, confirmExtra(response));
        return;
      }

      // Build enriched payload
      const payload = buildMessagePayload(msg, chatId);

      // Download photo if present (retry once on failure)
      if (msg.photo && msg.photo.length > 0) {
        const largest = msg.photo[msg.photo.length - 1]!;
        let photoData = await downloadPhoto(largest.file_id, config.botToken);
        if (!photoData) {
          photoData = await downloadPhoto(largest.file_id, config.botToken);
        }
        if (photoData) {
          if (!payload.attachments) payload.attachments = [];
          payload.attachments.push({
            type: "photo",
            data: photoData.data,
            mime_type: photoData.mime_type,
            filename: timestampFilename(),
            telegram_date: new Date(msg.date * 1000).toISOString(),
          });
        } else {
          // Photo download failed — append note to text
          payload.text = (payload.text ? payload.text + "\n" : "") +
            "[Photo attachment failed to download]";
        }
      }

      // Image sent as file (document) — Telegram preserves EXIF on these,
      // so GPS/camera metadata survives, unlike compressed photos.
      if (msg.document) {
        const mime = msg.document.mime_type ?? "";
        if (SUPPORTED_IMAGE_MIMES.has(mime)) {
          let fileData = await downloadPhoto(msg.document.file_id, config.botToken);
          if (!fileData) {
            fileData = await downloadPhoto(msg.document.file_id, config.botToken);
          }
          if (fileData) {
            const filename =
              msg.document.file_name?.replaceAll("/", "-") ?? timestampFilename();
            if (!payload.attachments) payload.attachments = [];
            payload.attachments.push({
              type: "photo",
              data: fileData.data,
              mime_type: mime,
              filename,
              telegram_date: new Date(msg.date * 1000).toISOString(),
            });
          } else {
            payload.text = (payload.text ? payload.text + "\n" : "") +
              "[File attachment failed to download]";
          }
        } else {
          payload.text = (payload.text ? payload.text + "\n" : "") +
            `[Unsupported file attachment: ${msg.document.file_name ?? mime ?? "unknown"}]`;
        }
      }

      if (config.streamResponses) {
        // Streaming: progressively push the accumulating buffer (and the fast
        // lane's stages) as a rich draft, then finalize. Drafts are ephemeral
        // 30s previews keyed by a non-zero draft_id; reusing the same draft_id
        // animates the update. Persist by sending the complete message via
        // sendFinal at the end.
        let buffered = "";
        let lastEdit = Date.now();
        const EDIT_INTERVAL_MS = 500;
        const draftId = (Date.now() % 2_000_000_000) || 1; // non-zero, stable per stream

        const pushDraft = async () => {
          try {
            await ctx.replyWithRichMessageDraft(
              { markdown: buffered },
              { draft_id: draftId },
            );
          } catch {
            // rate-limit / partial-parse errors are non-fatal mid-stream
          }
        };

        // The receipt is a persistent message, edited in place by later
        // updates. Frames are not ordered: an update can follow the reply's
        // text, and one can arrive with no receipt message to edit (its send
        // failed). That one is dropped: the final response carries the
        // latest receipt, which is then sent or redrawn below.
        let receiptMessage: Message | undefined;

        let response: MessageResponse;
        try {
          response = await streamMessage(payload, {
            onChunk: async (chunk) => {
              buffered += chunk;
              if (Date.now() - lastEdit > EDIT_INTERVAL_MS) {
                await pushDraft();
                lastEdit = Date.now();
              }
            },
            onStage: async (stage) => {
              try {
                await ctx.replyWithRichMessageDraft({ markdown: `_${stage}_` }, { draft_id: draftId });
              } catch {
                // a stage is a courtesy; losing one costs nothing
              }
            },
            onReceipt: async (receipt) => {
              if (receiptMessage) {
                await redrawReceipt(ctx, chatId, receiptMessage.message_id, receipt);
                return;
              }
              receiptMessage = await sendRich(ctx, buildReceiptRich(receipt));
            },
            onReceiptUpdate: async ({ receipt }) => {
              if (!receiptMessage) return;
              await redrawReceipt(ctx, chatId, receiptMessage.message_id, receipt);
            },
          });
        } catch {
          // Fall back to non-streaming on any stream error. The payload keeps
          // its message_id, so a turn the stream already started is answered
          // from that turn rather than run (and written) again.
          try {
            response = await api.sendMessage(payload);
          } catch (fallbackErr) {
            markActiveSpanError(fallbackErr);
            await ctx.reply("❌ Something went wrong. Is vault-server running?");
            return;
          }
        }

        if (response.awaiting_confirmation && response.pending_action_id) {
          setPendingConfirmation(chatId, response.pending_action_id);
        }
        setActiveSpanOutput(response.response);

        // Outside the fallback's try on purpose: a send that fails here must
        // not resend the message to the server.
        // Assigned inside the stream handlers, which control flow cannot see.
        const sent = receiptMessage as Message | undefined;
        if (sent && response.receipt) {
          // The final receipt carries every line's sync, including any whose
          // update the stream never delivered.
          await redrawReceipt(ctx, chatId, sent.message_id, response.receipt);
        }
        await sendFinal(ctx, chatId, response, sent !== undefined);
      } else {
        // Non-streaming path (default)
        const response = await api.sendMessage(payload);

        if (response.awaiting_confirmation && response.pending_action_id) {
          setPendingConfirmation(chatId, response.pending_action_id);
        }

        setActiveSpanOutput(response.response);
        await sendFinal(ctx, chatId, response, false);
      }
    } catch (err) {
      markActiveSpanError(err);
      await ctx.reply("❌ Something went wrong. Is vault-server running?");
    }
  },
);
