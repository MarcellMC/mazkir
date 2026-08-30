import { describe, it, expect } from "vitest";
import {
  formatTokens,
  formatCalendar,
  formatTime,
  progressBar,
} from "../../src/formatters/telegram.js";

describe("progressBar", () => {
  it("renders 50% as half filled", () => {
    expect(progressBar(50)).toBe("█████░░░░░");
  });
  it("renders 0%", () => {
    expect(progressBar(0)).toBe("░░░░░░░░░░");
  });
  it("renders 100%", () => {
    expect(progressBar(100)).toBe("██████████");
  });
});

describe("formatTime", () => {
  it("formats ISO datetime to HH:MM", () => {
    expect(formatTime("2026-03-02T14:30:00")).toBe("14:30");
  });
  it("returns 'All day' for date-only strings", () => {
    expect(formatTime("2026-03-02")).toBe("All day");
  });
});

describe("formatTokens", () => {
  it("shows token balance and milestone", () => {
    const result = formatTokens({ total: 42, today: 10, all_time: 42 });
    expect(result).toContain("42");
    expect(result).toContain("50");
    expect(result).toContain("8 to go");
  });
});

describe("formatCalendar", () => {
  it("shows events", () => {
    const result = formatCalendar([
      { id: "1", summary: "Meeting", start: "2026-03-02T10:00:00", end: "2026-03-02T11:00:00", completed: false, calendar: "Work" },
    ]);
    expect(result).toContain("Meeting");
    expect(result).toContain("10:00");
    expect(result).toContain("(Work)");
  });
  it("hides Mazkir calendar label", () => {
    const result = formatCalendar([
      { id: "1", summary: "Gym", start: "2026-03-02T07:00:00", end: "2026-03-02T08:00:00", completed: true, calendar: "Mazkir" },
    ]);
    expect(result).not.toContain("(Mazkir)");
  });
});
