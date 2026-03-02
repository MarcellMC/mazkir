import { describe, it, expect } from "vitest";
import {
  formatDay,
  formatTasks,
  formatHabits,
  formatGoals,
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

describe("formatTasks", () => {
  it("groups by priority", () => {
    const tasks = [
      { name: "urgent", status: "active", priority: 5 },
      { name: "low", status: "active", priority: 1 },
    ];
    const result = formatTasks(tasks);
    expect(result).toContain("🔴");
    expect(result).toContain("urgent");
    expect(result).toContain("🟢");
    expect(result).toContain("low");
  });
  it("shows empty message when no tasks", () => {
    const result = formatTasks([]);
    expect(result).toContain("No active tasks");
  });
});

describe("formatGoals", () => {
  it("shows progress bar", () => {
    const goals = [
      { name: "learn-rust", status: "active", priority: 4, progress: 70 },
    ];
    const result = formatGoals(goals);
    expect(result).toContain("█");
    expect(result).toContain("70%");
  });
});

describe("formatDay", () => {
  it("formats daily summary", () => {
    const result = formatDay({
      date: "2026-03-02",
      day_of_week: "Monday",
      tokens_earned: 10,
      tokens_total: 100,
      habits: [{ name: "gym", completed: true, streak: 5 }],
      calendar_events: [],
    });
    expect(result).toContain("Daily Note");
    expect(result).toContain("gym");
    expect(result).toContain("✅");
  });
});

describe("formatHabits", () => {
  it("shows habits with streaks", () => {
    const result = formatHabits([
      { name: "gym", frequency: "daily", streak: 5, tokens_per_completion: 10, completed_today: true },
      { name: "read", frequency: "daily", streak: 3, tokens_per_completion: 5, completed_today: false },
    ]);
    expect(result).toContain("gym");
    expect(result).toContain("✅");
    expect(result).toContain("⏳");
    expect(result).toContain("Average streak");
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
