import { Bot } from "grammy";
import type { Transformer } from "grammy";
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
import { noteOtherSend } from "./state/selected-date.js";

const tracer = trace.getTracer("mazkir.telegram-bot");

export const bot = new Bot(config.botToken);

// A transformer, not a per-call-site update: the hint has to be dropped by
// every send in the bot, and a rule that each new send site must opt into
// is a rule that will be missed. `day.ts` and the `day:` callback re-arm it
// immediately after their own send. Exported (rather than inlined into the
// `.use()` call) so it can be driven directly in a test with a stub `prev`.
export const dropSelectedDateHint: Transformer = async (prev, method, payload, signal) => {
  const result = await prev(method, payload, signal);
  const chatId = (payload as { chat_id?: number }).chat_id;
  if (chatId !== undefined) noteOtherSend(chatId);
  return result;
};

bot.api.config.use(dropSelectedDateHint);

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

  const inputText =
    message?.text ??
    message?.caption ??
    (ctx.callbackQuery?.data ? `callback:${ctx.callbackQuery.data}` : "");

  await tracer.startActiveSpan(
    "telegram.update",
    {
      attributes: {
        "openinference.span.kind": "CHAIN",
        "session.id": ctx.chat?.id !== undefined ? String(ctx.chat.id) : "",
        "user.id": ctx.from?.id !== undefined ? String(ctx.from.id) : "",
        "input.value": inputText,
        "input.mime_type": "text/plain",
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
        // Only mark OK if a downstream handler didn't already mark the span
        // ERROR (e.g. by catching an API failure before re-raising).
        const currentCode = (span as unknown as { status?: { code: SpanStatusCode } })
          .status?.code;
        if (currentCode !== SpanStatusCode.ERROR) {
          span.setStatus({ code: SpanStatusCode.OK });
        }
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

// Bot-wide error boundary. Without one, grammY rethrows and an unhandled
// rejection escapes the process — every callback handler is exposed, and
// `/day` newly introduced a synchronous throw path (a malformed payload
// reaching the formatter). Log it and carry on; the user still has the
// previous message on screen.
bot.catch((err) => {
  // err.error is unknown — grammY doesn't guarantee it's an Error. When it
  // is (the synchronous formatter throw this boundary exists to catch,
  // say), log the stack too; `String(err.error)` alone gives a message
  // with no line number to act on.
  const stack = err.error instanceof Error ? err.error.stack : undefined;
  logger.error(
    {
      event_type: "bot_error",
      update_id: err.ctx?.update?.update_id,
      chat_id: err.ctx?.chat?.id,
      err: String(err.error),
      ...(stack ? { stack } : {}),
    },
    "bot_error",
  );
});
