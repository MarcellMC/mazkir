import { describe, it, expect, vi, beforeEach } from "vitest";

const api = vi.hoisted(() => ({ receiptAction: vi.fn() }));
vi.mock("../../src/api/client.js", () => {
  class ApiError extends Error {
    constructor(readonly status: number, statusText: string) {
      super(`API error: ${status} ${statusText}`);
    }
  }
  return { api, ApiError };
});
const richMocks = vi.hoisted(() => ({ editRich: vi.fn(), sendRich: vi.fn() }));
vi.mock("../../src/bot-utils/send-rich.js", () => richMocks);

import { receiptHandlers } from "../../src/callbacks/receipt.js";
import { ApiError } from "../../src/api/client.js";
import {
  noteOpenQuestion,
  takeOpenQuestion,
  clearOpenQuestion,
  resetOpenQuestions,
} from "../../src/state/open-question.js";

async function fire(data: string) {
  const ctx: any = {
    callbackQuery: { data }, chat: { id: 1 }, update: { callback_query: { data } },
    answerCallbackQuery: vi.fn(), editMessageText: vi.fn(),
  };
  const next = vi.fn(async () => {});
  await receiptHandlers.middleware()(ctx, next);
  ctx.next = next;
  return ctx;
}

const receipt = { turn_id: "t0000beef", lines: [], undo: null, open_question: null, text: "" };

describe("receipt taps", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetOpenQuestions();
  });

  it("asks the server, redraws the receipt and shows the toast", async () => {
    api.receiptAction.mockResolvedValue({ receipt, toast: "Approved" });
    const ctx = await fire("rcpt:t0000beef:0:ok");
    expect(api.receiptAction).toHaveBeenCalledWith("t0000beef", "0", "ok");
    expect(richMocks.editRich).toHaveBeenCalledOnce();
    expect(ctx.answerCallbackQuery).toHaveBeenCalledWith({ text: "Approved" });
  });

  it("undo is the turn's u line", async () => {
    api.receiptAction.mockResolvedValue({ receipt, toast: "Undone" });
    await fire("rcpt:t0000beef:u:un");
    expect(api.receiptAction).toHaveBeenCalledWith("t0000beef", "u", "un");
  });

  it("says a failed tap failed rather than failing silently", async () => {
    api.receiptAction.mockRejectedValue(new Error("API error: 500"));
    const ctx = await fire("rcpt:t0000beef:0:ok");
    expect(ctx.answerCallbackQuery).toHaveBeenCalledWith({ text: "❌ That didn't work." });
    expect(richMocks.editRich).not.toHaveBeenCalled();
  });

  it("says a receipt that is gone is gone", async () => {
    api.receiptAction.mockRejectedValue(new ApiError(404, "Not Found"));
    const ctx = await fire("rcpt:t0000beef:0:ok");
    expect(ctx.answerCallbackQuery).toHaveBeenCalledWith({
      text: "That receipt is gone — receipts are kept for a day.",
    });
    expect(richMocks.editRich).not.toHaveBeenCalled();
  });

  it("a redraw that Telegram refuses still reports what the server did", async () => {
    api.receiptAction.mockResolvedValue({ receipt, toast: "Approved" });
    richMocks.editRich.mockRejectedValueOnce(new Error("Bad Request"));
    const ctx = await fire("rcpt:t0000beef:0:ok");
    expect(ctx.answerCallbackQuery).toHaveBeenCalledOnce();
    expect(ctx.answerCallbackQuery).toHaveBeenCalledWith({ text: "Approved" });
  });

  it("an empty toast answers the tap without text", async () => {
    api.receiptAction.mockResolvedValue({ receipt, toast: "" });
    const ctx = await fire("rcpt:t0000beef:0:ok");
    expect(ctx.answerCallbackQuery).toHaveBeenCalledWith(undefined);
  });

  it("a tap keeps the question the receipt is still waiting on", async () => {
    // The redraw is an edit, and every send but a chat action clears the
    // open question (bot.ts). Simulate that clearing here.
    richMocks.editRich.mockImplementationOnce(async () => clearOpenQuestion(1));
    api.receiptAction.mockResolvedValue({ receipt, toast: "Approved" });
    noteOpenQuestion(1, "A match · no time given. Reply with one.");
    await fire("rcpt:t0000beef:0:ok");
    expect(takeOpenQuestion(1)).toBe("A match · no time given. Reply with one.");
  });

  it("a tap arms no question when none was pending", async () => {
    api.receiptAction.mockResolvedValue({ receipt, toast: "Approved" });
    await fire("rcpt:t0000beef:0:ok");
    expect(takeOpenQuestion(1)).toBeUndefined();
  });

  it.each([
    "rcpt:../x:0:ok",
    "rcpt:t0000beef:0:zz",
    "rcpt:t0000beef:u:ok",
    "rcpt:t0000beef:0:un",
    "rcpt:t0000beef:12345:ok",
    "rcpt:T0000BEEF:0:ok",
    "rcpt:t0000beef:0:ok:extra",
  ])("ignores data that is not a receipt tap: %s", async (data) => {
    const ctx = await fire(data);
    expect(api.receiptAction).not.toHaveBeenCalled();
    expect(ctx.next).toHaveBeenCalled();   // left for the catch-all to answer
  });
});
