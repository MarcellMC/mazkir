import { Bot } from "grammy";
import { config } from "./config.js";
import {
  startCommand,
  dayCommand,
  tasksCommand,
  habitsCommand,
  goalsCommand,
  tokensCommand,
  calendarCommand,
  syncCommand,
  helpCommand,
} from "./commands/index.js";

export const bot = new Bot(config.botToken);

// Authorization middleware
bot.use(async (ctx, next) => {
  if (ctx.from?.id !== config.authorizedUserId) return;
  await next();
});

// Commands
bot.use(startCommand);
bot.use(dayCommand);
bot.use(tasksCommand);
bot.use(habitsCommand);
bot.use(goalsCommand);
bot.use(tokensCommand);
bot.use(calendarCommand);
bot.use(syncCommand);
bot.use(helpCommand);
