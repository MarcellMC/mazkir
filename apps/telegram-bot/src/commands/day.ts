import { Composer } from "grammy";
import { api } from "../api/client.js";
import { buildDayRich } from "../formatters/day-rich.js";
import { sendRich } from "../bot-utils/send-rich.js";
import { markActiveSpanError } from "../tracing-utils.js";

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
  // buildDayRich is inside the try, not beside it: it throws synchronously
  // on a malformed payload (a block missing `start`, say), and outside a
  // try that throw leaves the handler entirely. The `day:` callback wraps
  // the identical call.
  try {
    await sendRich(ctx, buildDayRich(data));
  } catch (err) {
    markActiveSpanError(err);
    await ctx.reply("❌ Failed to render the day.");
  }
});
