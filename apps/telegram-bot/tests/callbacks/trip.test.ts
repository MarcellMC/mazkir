import { describe, it, expect, vi, beforeEach } from "vitest";

const api = vi.hoisted(() => ({ tripTap: vi.fn() }));
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

import { tripHandlers, TRIP_TAP } from "../../src/callbacks/trip.js";
import { ApiError } from "../../src/api/client.js";
import { noteOpenQuestion, takeOpenQuestion, resetOpenQuestions } from "../../src/state/open-question.js";

async function fire(data: string) {
  const ctx: any = {
    callbackQuery: { data }, chat: { id: 1 }, update: { callback_query: { data } },
    answerCallbackQuery: vi.fn(), editMessageText: vi.fn(),
  };
  const next = vi.fn(async () => {});
  await tripHandlers.middleware()(ctx, next);
  ctx.next = next;
  return ctx;
}

const receipt = { turn_id: "1a2b3c4d", lines: [], undo: null, open_question: null, text: "" };

describe("trip taps", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetOpenQuestions();
  });

  it("matches only well-formed trip taps", () => {
    expect(TRIP_TAP.test("trip:1a2b3c4d:s1:a0")).toBe(true);
    expect(TRIP_TAP.test("trip:1a2b3c4d:all:ok")).toBe(true);
    expect(TRIP_TAP.test("trip:1a2b3c4d:trip:t")).toBe(true);
    expect(TRIP_TAP.test("trip:../x:s1:ok")).toBe(false);
    expect(TRIP_TAP.test("trip:1a2b3c4d:s1:a9")).toBe(false);
  });

  it("asks the server, toasts and redraws, restoring the pending question", async () => {
    api.tripTap.mockResolvedValue({ receipt, toast: "✓ Sauna", open_question: null });
    noteOpenQuestion(1, "held");
    const ctx = await fire("trip:1a2b3c4d:s1:a0");
    expect(api.tripTap).toHaveBeenCalledWith("1a2b3c4d", "s1", "a0");
    expect(ctx.answerCallbackQuery).toHaveBeenCalledWith({ text: "✓ Sauna" });
    expect(richMocks.editRich).toHaveBeenCalledOnce();
    expect(takeOpenQuestion(1)).toBe("held");
  });

  it("arms the returned open question for a ✎ Something else tap", async () => {
    api.tripTap.mockResolvedValue({ receipt: null, toast: "Type what it was", open_question: "What's this? [trip 1a2b3c4d · stop s1]" });
    await fire("trip:1a2b3c4d:s1:t");
    expect(richMocks.editRich).not.toHaveBeenCalled();
    expect(takeOpenQuestion(1)).toBe("What's this? [trip 1a2b3c4d · stop s1]");
  });

  it("toasts 'That trip is gone.' on 404", async () => {
    api.tripTap.mockRejectedValue(new ApiError(404, "Not Found"));
    const ctx = await fire("trip:1a2b3c4d:all:ok");
    expect(ctx.answerCallbackQuery).toHaveBeenCalledWith({ text: "That trip is gone." });
    expect(richMocks.editRich).not.toHaveBeenCalled();
  });

  it("any other failure says it didn't work and leaves the message", async () => {
    api.tripTap.mockRejectedValue(new Error("ECONNREFUSED"));
    const ctx = await fire("trip:1a2b3c4d:all:ok");
    expect(ctx.answerCallbackQuery).toHaveBeenCalledWith({ text: "❌ That didn't work." });
  });
});
