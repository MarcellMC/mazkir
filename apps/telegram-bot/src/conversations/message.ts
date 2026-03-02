import { Composer } from "grammy";
import { api } from "../api/client.js";

// Pending confirmations: chatId -> actionId
const pendingConfirmations = new Map<number, string>();

export const messageHandler = new Composer();

messageHandler.on("message:text", async (ctx) => {
  const text = ctx.message.text;
  const chatId = ctx.chat.id;

  // Skip commands (already handled)
  if (text.startsWith("/")) return;

  try {
    await ctx.replyWithChatAction("typing");

    let response;
    const pendingActionId = pendingConfirmations.get(chatId);
    if (pendingActionId) {
      pendingConfirmations.delete(chatId);
      response = await api.sendConfirmation(chatId, pendingActionId, text);
    } else {
      response = await api.sendMessage(text, chatId);
    }

    if (response.awaiting_confirmation && response.pending_action_id) {
      pendingConfirmations.set(chatId, response.pending_action_id);
    }

    await ctx.reply(response.response, { parse_mode: "HTML" });
  } catch {
    await ctx.reply("❌ Something went wrong. Is vault-server running?");
  }
});
