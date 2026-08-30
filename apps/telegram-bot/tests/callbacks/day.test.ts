import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("../../src/config.js", () => ({
  config: {
    botToken: "test-token",
    vaultServerUrl: "http://localhost:8000",
    vaultServerApiKey: "test-key",
    authorizedUserId: 123,
    webappUrl: "http://localhost:5173",
    logLevel: "INFO",
  },
}));

vi.mock("../../src/api/client.js", () => ({
  api: { getDaily: vi.fn() },
}));

vi.mock("../../src/bot-utils/send-rich.js", () => ({
  sendRich: vi.fn(),
  editRich: vi.fn(),
  richToPlainText: vi.fn(() => ""),
}));

const { Context, Api } = await import("grammy");
const { callbackHandlers } = await import("../../src/callbacks/index.js");
const { api } = await import("../../src/api/client.js");
const { editRich, sendRich } = await import("../../src/bot-utils/send-rich.js");

const DAY = {
  date: "2026-08-30",
  tokens_today: 0,
  tokens_total: 0,
  blocks: [],
  gaps: [],
  coverage: { covered_minutes: 0, unaccounted_minutes: 0, elapsed_minutes: 0 },
  todos: [],
  notes: [],
};

/** A real grammY Context, so the `callbackQuery(/^day:(.+)$/)` filter and
 *  `ctx.match` behave exactly as they do in production. Only the two API
 *  calls the handler makes are stubbed. */
function ctxFor(data: string) {
  const update = {
    update_id: 1,
    callback_query: {
      id: "cbq-1",
      from: { id: 123, is_bot: false, first_name: "M" },
      chat_instance: "ci",
      data,
      message: {
        message_id: 7,
        date: 0,
        chat: { id: 123, type: "private" as const, first_name: "M" },
      },
    },
  };
  const ctx = new Context(
    update as never,
    new Api("test-token"),
    { id: 1, is_bot: true, first_name: "bot", username: "bot", can_join_groups: true,
      can_read_all_group_messages: false, supports_inline_queries: false,
      can_connect_to_business: false, has_main_web_app: false },
  );
  ctx.answerCallbackQuery = vi.fn().mockResolvedValue(true) as never;
  ctx.editMessageText = vi.fn().mockResolvedValue(true) as never;
  return ctx;
}

async function dispatch(ctx: unknown) {
  await callbackHandlers.middleware()(ctx as never, async () => {});
}

describe("the day: callback", () => {
  beforeEach(() => {
    vi.mocked(api.getDaily).mockReset().mockResolvedValue(DAY as never);
    vi.mocked(editRich).mockReset();
    vi.mocked(sendRich).mockReset();
  });

  it("edits the existing message rather than posting a new one", async () => {
    // Spec §7 names this test: navigation re-renders one message, so a new
    // message per tap would bury the day under a stack of stale copies.
    const ctx = ctxFor("day:2026-08-30");
    await dispatch(ctx);

    expect(api.getDaily).toHaveBeenCalledWith("2026-08-30");
    expect(editRich).toHaveBeenCalledOnce();
    expect(sendRich).not.toHaveBeenCalled();
    // The rendered day, not the raw payload.
    expect(vi.mocked(editRich).mock.calls[0]![1]).toHaveProperty("html");
  });

  it("attaches the Tasks/Habits/Goals cross-view keyboard, with no Calendar button", async () => {
    const ctx = ctxFor("day:2026-08-30");
    await dispatch(ctx);

    const extra = vi.mocked(editRich).mock.calls[0]![2] as
      | { reply_markup?: { inline_keyboard: { text: string; callback_data: string }[][] } }
      | undefined;
    const buttons = extra?.reply_markup?.inline_keyboard.flat() ?? [];
    expect(buttons.map((b) => b.callback_data)).toEqual([
      "nav:tasks", "nav:habits", "nav:goals",
    ]);
    expect(buttons.some((b) => b.callback_data === "nav:calendar")).toBe(false);
  });

  it("maps day:today to no date parameter", async () => {
    // `today` stays a token rather than a date so a message tapped after
    // midnight still resolves to the server's idea of today.
    await dispatch(ctxFor("day:today"));
    expect(api.getDaily).toHaveBeenCalledWith(undefined);
  });

  it("answers the callback query so the button stops spinning", async () => {
    const ctx = ctxFor("day:2026-08-30");
    await dispatch(ctx);
    expect(ctx.answerCallbackQuery).toHaveBeenCalledOnce();
  });

  it("reports a fetch failure by editing, and contains it", async () => {
    vi.mocked(api.getDaily).mockRejectedValueOnce(new Error("server down"));
    const ctx = ctxFor("day:2026-08-30");

    await expect(dispatch(ctx)).resolves.toBeUndefined();

    expect(editRich).not.toHaveBeenCalled();
    expect(ctx.editMessageText).toHaveBeenCalledWith("❌ Failed to load the day.");
  });

  it("swallows a failure to report the failure", async () => {
    // The error report is itself an edit and can itself be rejected — as an
    // unhandled rejection it would escape the middleware entirely.
    vi.mocked(api.getDaily).mockRejectedValueOnce(new Error("server down"));
    const ctx = ctxFor("day:2026-08-30");
    ctx.editMessageText = vi.fn().mockRejectedValue(new Error("not modified")) as never;

    await expect(dispatch(ctx)).resolves.toBeUndefined();
  });
});
