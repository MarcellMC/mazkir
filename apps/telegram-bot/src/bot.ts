import { Bot } from "grammy";
import { trace, SpanStatusCode } from "@opentelemetry/api";
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
import { callbackHandlers } from "./callbacks/index.js";
import { messageHandler } from "./conversations/message.js";
import { logger } from "./logger.js";

const tracer = trace.getTracer("mazkir.telegram-bot");

export const bot = new Bot(config.botToken);

// Authorization + per-update logging middleware
bot.use(async (ctx, next) => {
  if (ctx.from?.id !== config.authorizedUserId) {
    logger.warn(
      {
        event_type: "update_unauthorized",
        from_id: ctx.from?.id,
        update_id: ctx.update.update_id,
      },
      "update_unauthorized",
    );
    return;
  }
  const message = ctx.message;
  const kind = message?.text
    ? "text"
    : message?.photo
      ? "photo"
      : message?.location
        ? "location"
        : ctx.callbackQuery
          ? "callback"
          : "other";

  await tracer.startActiveSpan(
    "telegram.update",
    {
      attributes: {
        "telegram.update_id": ctx.update.update_id,
        "telegram.chat_id": ctx.chat?.id,
        "telegram.from_id": ctx.from?.id,
        "telegram.kind": kind,
        "telegram.text_length": message?.text?.length ?? 0,
      },
    },
    async (span) => {
      logger.info(
        {
          event_type: "update_received",
          update_id: ctx.update.update_id,
          chat_id: ctx.chat?.id,
          from_id: ctx.from?.id,
          kind,
          text_length: message?.text?.length ?? 0,
        },
        "update_received",
      );
      try {
        await next();
        span.setStatus({ code: SpanStatusCode.OK });
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        span.recordException(err instanceof Error ? err : new Error(message));
        span.setStatus({ code: SpanStatusCode.ERROR, message });
        throw err;
      } finally {
        span.end();
      }
    },
  );
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

// Callbacks (inline keyboard buttons)
bot.use(callbackHandlers);

// NL message handler (catch-all, must be last)
bot.use(messageHandler);
