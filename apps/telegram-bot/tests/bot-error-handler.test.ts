import { describe, it, expect, vi } from "vitest";

vi.mock("./../src/config.js", () => ({
  config: {
    botToken: "test-token",
    vaultServerUrl: "http://localhost:8000",
    vaultServerApiKey: "test-key",
    authorizedUserId: 123,
    webappUrl: "http://localhost:5173",
    logLevel: "INFO",
  },
}));

const errorLog = vi.fn();
vi.mock("./../src/logger.js", () => ({
  logger: { error: errorLog, warn: vi.fn(), info: vi.fn(), debug: vi.fn() },
}));

const { bot } = await import("../src/bot.js");
const { BotError } = await import("grammy");

describe("bot.catch", () => {
  it("logs an unhandled handler error instead of letting it escape", async () => {
    // No error boundary existed anywhere in the bot: grammY rethrows, and an
    // unhandled rejection from any callback handler took the process with it.
    const err = new BotError(new Error("boom"), { update: { update_id: 9 } } as never);

    // The handler is synchronous, so it must simply not throw.
    expect(() => bot.errorHandler(err)).not.toThrow();

    expect(errorLog).toHaveBeenCalledOnce();
    expect(errorLog.mock.calls[0]![0]).toMatchObject({
      event_type: "bot_error",
      update_id: 9,
    });
    expect(String(errorLog.mock.calls[0]![0].err)).toContain("boom");
  });
});
