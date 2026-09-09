import { describe, it, expect, beforeEach } from "vitest";
import { dropSelectedDateHint } from "../src/bot.js";
import {
  setSelectedDate, noteDayView, getSelectedDate, resetSelectedDates,
} from "../src/state/selected-date.js";

/**
 * `dropSelectedDateHint` is the literal mechanism preventing the hint's
 * two-sided failure mode (never applying, or applying long after the user
 * forgot which day was selected). Everything else in selected-date.test.ts
 * exercises `noteOtherSend` directly; this drives the registered
 * transformer itself, the way `bot.api.config.use` actually calls it.
 */
describe("dropSelectedDateHint transformer", () => {
  beforeEach(() => resetSelectedDates());

  it("drops the hint on any outgoing call carrying a chat_id", async () => {
    setSelectedDate(42, "2026-08-20");
    noteDayView(42);
    expect(getSelectedDate(42)).toBe("2026-08-20");

    const prevResult = { ok: true as const, result: true };
    const prev = async () => prevResult;

    const result = await dropSelectedDateHint(
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

    await dropSelectedDateHint(prev, "sendMessage", { chat_id: 1, text: "hi" } as never, undefined);

    expect(getSelectedDate(1)).toBeUndefined();
    expect(getSelectedDate(2)).toBe("2026-08-21");
  });

  it("does not touch the hint for a call with no chat_id", async () => {
    setSelectedDate(1, "2026-08-20");
    noteDayView(1);

    const prev = async () => ({ ok: true as const, result: true });

    await dropSelectedDateHint(prev, "getMe", {} as never, undefined);

    expect(getSelectedDate(1)).toBe("2026-08-20");
  });
});
