import { Composer } from "grammy";
import { api } from "../api/client.js";
import { buildDayRich } from "../formatters/day-rich.js";
import { sendRich } from "../bot-utils/send-rich.js";
import { buildNavKeyboard } from "../keyboards/nav.js";
import { markActiveSpanError } from "../tracing-utils.js";
import { setSelectedDate, noteDayView } from "../state/selected-date.js";

export const dayCommand = new Composer();

dayCommand.command("day", async (ctx) => {
  // Fetch and send are reported separately: a bare catch around both used to
  // report a Telegram send failure as "is vault-server running?", pointing
  // the user at the wrong cause.
  let data;
  try {
    data = await api.getDaily();
  } catch (err) {
    markActiveSpanError(err);
    await ctx.reply("❌ Failed to load the day. Is vault-server running?");
    return;
  }
  // buildDayRich (throws synchronously on a malformed payload — a block
  // missing `start`, say) and sendRich (a Telegram send failure) get their
  // own try/catch pairs so each reports its own cause. Collapsing them
  // back into one try is exactly the conflation this file's own comment
  // above warns against: a send failure would again read as a render bug.
  let rich;
  try {
    rich = buildDayRich(data);
  } catch (err) {
    markActiveSpanError(err);
    await ctx.reply("❌ Failed to render the day.");
    return;
  }
  setSelectedDate(ctx.chat!.id, data.date);
  try {
    await sendRich(ctx, rich, { reply_markup: buildNavKeyboard("day") });
    noteDayView(ctx.chat!.id);
  } catch (err) {
    markActiveSpanError(err);
    await ctx.reply("❌ Failed to send the day.");
  }
});
