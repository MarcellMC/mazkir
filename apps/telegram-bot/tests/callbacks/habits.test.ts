import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("../../src/config.js", () => ({
  config: {
    botToken: "test-token",
    vaultServerUrl: "http://localhost:8000",
    vaultServerApiKey: "test-key",
    authorizedUserId: 123,
    webappUrl: "http://localhost:5173",
    logLevel: "INFO",
    vaultTimezone: "Asia/Jerusalem",
  },
}));

vi.mock("../../src/api/client.js", () => ({
  api: { completeHabit: vi.fn(), listHabits: vi.fn() },
}));

vi.mock("../../src/bot-utils/send-rich.js", () => ({
  sendRich: vi.fn(),
  editRich: vi.fn(),
  richToPlainText: vi.fn(() => ""),
}));

const { Context, Api } = await import("grammy");
const { callbackHandlers } = await import("../../src/callbacks/index.js");
const { api } = await import("../../src/api/client.js");
const { editRich } = await import("../../src/bot-utils/send-rich.js");

const HABITS = [
  { name: "Dog walk", frequency: "daily", streak: 3, completed_today: true },
  { name: "Workout", frequency: "daily", streak: 1, completed_today: false },
];

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

function navButtons(callIndex = 0) {
  const extra = vi.mocked(editRich).mock.calls[callIndex]![2] as
    | { reply_markup?: { inline_keyboard: { text: string; callback_data: string }[][] } }
    | undefined;
  return (extra?.reply_markup?.inline_keyboard.flat() ?? []).map((b) => b.callback_data);
}

describe("the habit:complete: callback", () => {
  beforeEach(() => {
    vi.mocked(api.completeHabit).mockReset().mockResolvedValue({
      already_completed: false, name: "Workout", completions_today: 1,
      daily_target: 1, old_streak: 1, new_streak: 2, tokens_earned: 5,
      new_token_total: 55, target_met: true,
    } as never);
    vi.mocked(api.listHabits).mockReset().mockResolvedValue(HABITS as never);
    vi.mocked(editRich).mockReset();
  });

  it("keeps the cross-view keyboard after a completion", async () => {
    // Regression: this handler used to re-render with
    // `editMessageText(formatHabits(habits), { parse_mode: "HTML" })` — no
    // reply_markup at all — so completing a habit stripped every button from
    // the message and the user had to re-issue /habits to get them back.
    await dispatch(ctxFor("habit:complete:Workout"));

    expect(api.completeHabit).toHaveBeenCalledWith("Workout");
    expect(editRich).toHaveBeenCalledOnce();
    expect(navButtons()).toEqual(["nav:day", "nav:tasks", "nav:goals"]);
  });

  it("re-renders the list as rich content, so in-body buttons survive too", async () => {
    // The completion buttons are in the message body now, not the keyboard.
    // A plain-text re-render would drop them silently.
    await dispatch(ctxFor("habit:complete:Workout"));
    const msg = vi.mocked(editRich).mock.calls[0]![1] as { html?: string };
    expect(msg).toHaveProperty("html");
    expect(msg.html).toContain("Habit Tracker");
  });

  it("says what the completion paid", async () => {
    // The response used to be typed `unknown` and discarded, so the toast was
    // always "✅ Workout completed!" — no way to tell an award from a no-op.
    const ctx = ctxFor("habit:complete:Workout");
    await dispatch(ctx);

    expect(ctx.answerCallbackQuery).toHaveBeenCalledWith({
      text: "✅ Workout · +5 tokens · streak 2",
    });
  });

  it("does not claim an award on a repeat tap", async () => {
    vi.mocked(api.completeHabit).mockResolvedValueOnce({
      already_completed: true, name: "Workout", streak: 2,
      completions_today: 2, daily_target: 2,
    } as never);
    const ctx = ctxFor("habit:complete:Workout");

    await dispatch(ctx);

    expect(ctx.answerCallbackQuery).toHaveBeenCalledWith({
      text: "Already done today — Workout (2/2)",
    });
    // The list is still refreshed: the tapped button should go away.
    expect(editRich).toHaveBeenCalledOnce();
  });

  it("reports a failure without touching the message", async () => {
    vi.mocked(api.completeHabit).mockRejectedValueOnce(new Error("nope"));
    const ctx = ctxFor("habit:complete:Workout");

    await expect(dispatch(ctx)).resolves.toBeUndefined();

    expect(editRich).not.toHaveBeenCalled();
    expect(ctx.answerCallbackQuery).toHaveBeenCalledWith({
      text: "❌ Failed to complete habit",
    });
  });
});

describe("the nav:habits callback", () => {
  beforeEach(() => {
    vi.mocked(api.listHabits).mockReset().mockResolvedValue(HABITS as never);
    vi.mocked(editRich).mockReset();
  });

  it("renders rich content with the habits cross-view keyboard", async () => {
    await dispatch(ctxFor("nav:habits"));
    expect(editRich).toHaveBeenCalledOnce();
    expect(vi.mocked(editRich).mock.calls[0]![1]).toHaveProperty("html");
    expect(navButtons()).toEqual(["nav:day", "nav:tasks", "nav:goals"]);
  });
});
