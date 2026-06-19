import { Composer } from "grammy";
import type { Message } from "grammy/types";
import type { Attachment, ReplyContext, ForwardContext } from "@mazkir/shared-types";
import { api, streamMessage } from "../api/client.js";
import { config } from "../config.js";
import { markActiveSpanError, setActiveSpanOutput } from "../tracing-utils.js";
import { sendRich } from "../bot-utils/send-rich.js";

// Pending confirmations: chatId -> actionId
const pendingConfirmations = new Map<number, string>();

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
  if (msg.reply_to_message?.text) {
    reply_to = {
      text: msg.reply_to_message.text,
      from: msg.reply_to_message.from?.is_bot ? "assistant" : "user",
    };
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

  return {
    text,
    chat_id: chatId,
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
      const pendingActionId = pendingConfirmations.get(chatId);
      if (pendingActionId && msg.text && !msg.photo && !msg.location) {
        pendingConfirmations.delete(chatId);
        const response = await api.sendConfirmation(
          chatId,
          pendingActionId,
          text,
        );
        if (response.awaiting_confirmation && response.pending_action_id) {
          pendingConfirmations.set(chatId, response.pending_action_id);
        }
        setActiveSpanOutput(response.response);
        await ctx.reply(response.response, { parse_mode: "HTML" });
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
        // Streaming: progressively push the accumulating buffer as a rich draft,
        // then finalize. editMessageText is NOT used (it can't edit rich content).
        // Drafts are ephemeral 30s previews keyed by a non-zero draft_id; reusing
        // the same draft_id animates the update. Persist by sending the complete
        // message via sendRich at the end.
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

        try {
          const response = await streamMessage(payload, async (chunk) => {
            buffered += chunk;
            if (Date.now() - lastEdit > EDIT_INTERVAL_MS) {
              await pushDraft();
              lastEdit = Date.now();
            }
          });

          if (response.awaiting_confirmation && response.pending_action_id) {
            pendingConfirmations.set(chatId, response.pending_action_id);
          }
          setActiveSpanOutput(response.response);

          // Finalize as a full rich message (catch-all → plain text on failure).
          await sendRich(ctx, { markdown: response.response });
        } catch {
          // Fall back to non-streaming on any stream error.
          try {
            const response = await api.sendMessage(payload);
            if (response.awaiting_confirmation && response.pending_action_id) {
              pendingConfirmations.set(chatId, response.pending_action_id);
            }
            setActiveSpanOutput(response.response);
            await sendRich(ctx, { markdown: response.response });
          } catch (fallbackErr) {
            markActiveSpanError(fallbackErr);
            await ctx.reply("❌ Something went wrong. Is vault-server running?");
          }
        }
      } else {
        // Non-streaming path (default)
        const response = await api.sendMessage(payload);

        if (response.awaiting_confirmation && response.pending_action_id) {
          pendingConfirmations.set(chatId, response.pending_action_id);
        }

        setActiveSpanOutput(response.response);
        // Agent already emits markdown — send it through as a rich message.
        await sendRich(ctx, { markdown: response.response });
      }
    } catch (err) {
      markActiveSpanError(err);
      await ctx.reply("❌ Something went wrong. Is vault-server running?");
    }
  },
);
