import { describe, it, expect, beforeEach } from "vitest";
import {
  getSelectedDate, setSelectedDate, noteDayView, noteOtherSend, resetSelectedDates,
} from "../../src/state/selected-date.js";

describe("selected date hint", () => {
  beforeEach(() => resetSelectedDates());

  it("is absent before any day view", () => {
    expect(getSelectedDate(1)).toBeUndefined();
  });

  it("is offered after a day view renders", () => {
    setSelectedDate(1, "2026-08-20");
    noteDayView(1);
    expect(getSelectedDate(1)).toBe("2026-08-20");
  });

  it("is dropped once the bot sends anything else", () => {
    // A day view scrolled off behind other output is no longer what the
    // user is looking at — and a date they have forgotten selecting must
    // not silently steer a much later message.
    setSelectedDate(1, "2026-08-20");
    noteDayView(1);
    noteOtherSend(1);
    expect(getSelectedDate(1)).toBeUndefined();
  });

  it("comes back when a new day view renders", () => {
    setSelectedDate(1, "2026-08-20");
    noteDayView(1);
    noteOtherSend(1);
    setSelectedDate(1, "2026-08-21");
    noteDayView(1);
    expect(getSelectedDate(1)).toBe("2026-08-21");
  });

  it("keeps chats separate", () => {
    setSelectedDate(1, "2026-08-20");
    noteDayView(1);
    setSelectedDate(2, "2026-08-21");
    noteDayView(2);
    noteOtherSend(1);
    expect(getSelectedDate(1)).toBeUndefined();
    expect(getSelectedDate(2)).toBe("2026-08-21");
  });
});
