import { Composer } from "grammy";
import { api } from "../api/client.js";
import { formatTokens } from "../formatters/telegram.js";

export const tokensCommand = new Composer();

tokensCommand.command("tokens", async (ctx) => {
  try {
    const data = await api.getTokens();
    await ctx.reply(formatTokens(data), { parse_mode: "HTML" });
  } catch {
    await ctx.reply("❌ Failed to load tokens.");
  }
});
