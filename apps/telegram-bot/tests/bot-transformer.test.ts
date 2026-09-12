import { describe, it, expect, beforeEach, vi } from "vitest";
import { dropPerMessageHints } from "../src/bot.js";
import {
  setSelectedDate, noteDayView, getSelectedDate, resetSelectedDates,
} from "../src/state/selected-date.js";

/**
 * `dropPerMessageHints` is the literal mechanism preventing the hint's
 * two-sided failure mode (never applying, or applying long after the user
 * forgot which day was selected). Everything else in selected-date.test.ts
 * exercises `noteOtherSend` directly; this drives the registered
 * transformer itself, the way `bot.api.config.use` actually calls it.
 */
describe("dropPerMessageHints transformer", () => {
  beforeEach(() => resetSelectedDates());

  it("drops the hint on any outgoing call carrying a chat_id", async () => {
    setSelectedDate(42, "2026-08-20");
    noteDayView(42);
    expect(getSelectedDate(42)).toBe("2026-08-20");

    const prevResult = { ok: true as const, result: true };
    const prev = async () => prevResult;

    const result = await dropPerMessageHints(
      prev,
      "sendMessage",
      { chat_id: 42, text: "hi" } as never,
      undefined,
    );

    expect(result).toBe(prevResult);
    expect(getSelectedDate(42)).toBeUndefined();
  });

  it("leaves other chats' hints alone", async () => {
    setSelectedDate(1, "2026-08-20");
    noteDayView(1);
    setSelectedDate(2, "2026-08-21");
    noteDayView(2);

    const prev = async () => ({ ok: true as const, result: true });

    await dropPerMessageHints(prev, "sendMessage", { chat_id: 1, text: "hi" } as never, undefined);

    expect(getSelectedDate(1)).toBeUndefined();
    expect(getSelectedDate(2)).toBe("2026-08-21");
  });

  it("does not touch the hint for a call with no chat_id", async () => {
    setSelectedDate(1, "2026-08-20");
    noteDayView(1);

    const prev = async () => ({ ok: true as const, result: true });

    await dropPerMessageHints(prev, "getMe", {} as never, undefined);

    expect(getSelectedDate(1)).toBe("2026-08-20");
  });
});

describe("dropPerMessageHints and the open question", () => {
  it("clears a pending question when the bot sends something else", async () => {
    const { noteOpenQuestion, takeOpenQuestion, resetOpenQuestions } = await import(
      "../src/state/open-question.js"
    );
    resetOpenQuestions();
    noteOpenQuestion(1, "what was 15:00–17:30?");

    const prev = vi.fn().mockResolvedValue({ ok: true, result: {} });
    await dropPerMessageHints(prev, "sendMessage", { chat_id: 1, text: "hi" } as never, undefined);

    // An unanswered question stops being what the next message answers once
    // the bot has said something else.
    expect(takeOpenQuestion(1)).toBeUndefined();
  });
});

describe("the typing indicator is not the bot saying something", () => {
  // The hole that made the 2026-09-12 20:03 report identical to the 17:56
  // one despite the fix being deployed. The NL handler's first act is
  // `ctx.replyWithChatAction("typing")`, which carries a chat_id and so ran
  // this transformer — destroying both hints before buildMessagePayload read
  // them, twenty lines later. Asserted here, at the transformer, because
  // buildMessagePayload tested in isolation passes either way.
  async function fire(method: string) {
    const prev = vi.fn().mockResolvedValue({ ok: true, result: {} });
    await dropPerMessageHints(prev, method, { chat_id: 1, text: "x" } as never, undefined);
  }

  beforeEach(async () => {
    const { resetSelectedDates } = await import("../src/state/selected-date.js");
    const { resetOpenQuestions } = await import("../src/state/open-question.js");
    resetSelectedDates();
    resetOpenQuestions();
  });

  it("keeps both hints alive through a typing indicator", async () => {
    const { setSelectedDate, noteDayView, getSelectedDate } = await import(
      "../src/state/selected-date.js"
    );
    const { noteOpenQuestion, takeOpenQuestion } = await import(
      "../src/state/open-question.js"
    );
    setSelectedDate(1, "2026-09-12");
    noteDayView(1);
    noteOpenQuestion(1, "15:00–17:30 — what was it?");

    await fire("sendChatAction");

    expect(getSelectedDate(1)).toBe("2026-09-12");
    expect(takeOpenQuestion(1)).toBe("15:00–17:30 — what was it?");
  });

  it("still drops both when the bot actually sends a message", async () => {
    // The floor: excluding the typing indicator must not turn the transformer
    // off, or a stale hint rides along on an unrelated message.
    const { setSelectedDate, noteDayView, getSelectedDate } = await import(
      "../src/state/selected-date.js"
    );
    const { noteOpenQuestion, takeOpenQuestion } = await import(
      "../src/state/open-question.js"
    );
    setSelectedDate(1, "2026-09-12");
    noteDayView(1);
    noteOpenQuestion(1, "15:00–17:30 — what was it?");

    await fire("sendMessage");

    expect(getSelectedDate(1)).toBeUndefined();
    expect(takeOpenQuestion(1)).toBeUndefined();
  });
});
