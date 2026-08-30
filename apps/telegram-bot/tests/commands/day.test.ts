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

vi.mock("../../src/api/client.js", () => ({ api: { getDaily: vi.fn() } }));
vi.mock("../../src/bot-utils/send-rich.js", () => ({
  sendRich: vi.fn(),
  editRich: vi.fn(),
  richToPlainText: vi.fn(() => ""),
}));

const { Context, Api } = await import("grammy");
const { dayCommand } = await import("../../src/commands/day.js");
const { api } = await import("../../src/api/client.js");
const { sendRich } = await import("../../src/bot-utils/send-rich.js");

const DAY = {
  date: "2026-08-30", tokens_today: 0, tokens_total: 0,
  blocks: [], gaps: [],
  coverage: { covered_minutes: 0, unaccounted_minutes: 0, elapsed_minutes: 0 },
  todos: [], notes: [],
};

function ctxForCommand() {
  const update = {
    update_id: 1,
    message: {
      message_id: 5, date: 0, text: "/day",
      entities: [{ type: "bot_command" as const, offset: 0, length: 4 }],
      from: { id: 123, is_bot: false, first_name: "M" },
      chat: { id: 123, type: "private" as const, first_name: "M" },
    },
  };
  const ctx = new Context(
    update as never,
    new Api("test-token"),
    { id: 1, is_bot: true, first_name: "bot", username: "bot", can_join_groups: true,
      can_read_all_group_messages: false, supports_inline_queries: false,
      can_connect_to_business: false, has_main_web_app: false },
  );
  ctx.reply = vi.fn().mockResolvedValue(true) as never;
  return ctx;
}

async function dispatch(ctx: unknown) {
  await dayCommand.middleware()(ctx as never, async () => {});
}

describe("/day", () => {
  beforeEach(() => {
    vi.mocked(api.getDaily).mockReset().mockResolvedValue(DAY as never);
    vi.mocked(sendRich).mockReset();
  });

  it("renders the day", async () => {
    const ctx = ctxForCommand();
    await dispatch(ctx);
    expect(sendRich).toHaveBeenCalledOnce();
    expect(ctx.reply).not.toHaveBeenCalled();
  });

  it("reports a fetch failure as a server problem", async () => {
    vi.mocked(api.getDaily).mockRejectedValueOnce(new Error("ECONNREFUSED"));
    const ctx = ctxForCommand();
    await dispatch(ctx);
    expect(ctx.reply).toHaveBeenCalledWith(
      "❌ Failed to load the day. Is vault-server running?");
  });

  it("contains a malformed payload instead of throwing out of the handler", async () => {
    // buildDayRich reads data.coverage.covered_minutes synchronously. Called
    // outside the try, this threw straight past the handler.
    vi.mocked(api.getDaily).mockResolvedValueOnce({ date: "2026-08-30" } as never);
    const ctx = ctxForCommand();

    await expect(dispatch(ctx)).resolves.toBeUndefined();

    expect(ctx.reply).toHaveBeenCalledWith("❌ Failed to render the day.");
  });
});
