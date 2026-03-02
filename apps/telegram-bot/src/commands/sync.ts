import { Composer } from "grammy";
import { api } from "../api/client.js";

export const syncCommand = new Composer();

syncCommand.command("sync_calendar", async (ctx) => {
  try {
    await api.syncCalendar();
    await ctx.reply("✅ Calendar synced successfully!", { parse_mode: "HTML" });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "";
    if (msg.includes("503")) {
      await ctx.reply("⚠️ Calendar sync is not configured on the server.");
    } else {
      await ctx.reply("❌ Failed to sync calendar.");
    }
  }
});
