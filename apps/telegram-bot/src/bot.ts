import { Bot } from "grammy";
import { config } from "./config.js";

export const bot = new Bot(config.botToken);

// Authorization middleware — reject messages from unauthorized users
bot.use(async (ctx, next) => {
  if (ctx.from?.id !== config.authorizedUserId) {
    return; // silently ignore
  }
  await next();
});
