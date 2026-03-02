import { Composer } from "grammy";
import { api } from "../api/client.js";
import { formatCalendar } from "../formatters/telegram.js";

export const calendarCommand = new Composer();

calendarCommand.command("calendar", async (ctx) => {
  try {
    const events = await api.getCalendarEvents();
    await ctx.reply(formatCalendar(events), { parse_mode: "HTML" });
  } catch {
    await ctx.reply("❌ Failed to load calendar.");
  }
});
