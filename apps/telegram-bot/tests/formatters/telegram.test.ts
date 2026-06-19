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
  it("numbers tasks sequentially across priority groups", () => {
    const tasks = [
      { name: "urgent", status: "active", priority: 5 },
      { name: "medium", status: "active", priority: 3 },
      { name: "low", status: "active", priority: 1 },
    ];
    const result = formatTasks(tasks);
    expect(result).toContain("1. ⏳ urgent");
    expect(result).toContain("2. ⏳ medium");
    expect(result).toContain("3. ⏳ low");
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
  it("formats daily summary with schedule and notes", () => {
    const result = formatDay({
      date: "2026-03-02",
      tokens_today: 10,
      tokens_total: 100,
      schedule: [
        { start: "2026-03-02T09:00:00", title: "Meeting", source: "calendar", completed: false, calendar_name: "Work" },
        { start: "07:00", title: "gym", source: "habit", completed: true },
      ],
      notes: [{ text: "Remember to call mom" }],
    });
    expect(result).toContain("Daily Note");
    expect(result).toContain("10");
    expect(result).toContain("Meeting");
    expect(result).toContain("(Work)");
    expect(result).toContain("gym");
    expect(result).toContain("✅");
    expect(result).toContain("Remember to call mom");
  });

  it("shows photo notes with caption", () => {
    const result = formatDay({
      date: "2026-03-02",
      tokens_today: 0,
      tokens_total: 0,
      schedule: [],
      notes: [{ caption: "sunset photo", photo_path: "/data/media/photo.jpg" }],
    });
    expect(result).toContain("📷 sunset photo");
  });

  it("drops calendar_name when it is Mazkir", () => {
    const result = formatDay({
      date: "2026-03-02",
      tokens_today: 0,
      tokens_total: 0,
      schedule: [{ start: "08:00", title: "Gym", source: "habit", completed: false, calendar_name: "Mazkir" }],
      notes: [],
    });
    expect(result).not.toContain("(Mazkir)");
  });

  it("returns shape without habits/calendar_events sections", () => {
    const result = formatDay({
      date: "2026-03-02",
      tokens_today: 5,
      tokens_total: 50,
      schedule: [],
      notes: [],
    });
    expect(result).toContain("Daily Note");
    expect(result).not.toContain("Habits");
    expect(result).not.toContain("calendar_events");
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
  it("returns rich html with balance and next milestone", () => {
    const msg = formatTokens({ total: 42, today: 10, all_time: 42 });
    expect(msg.html).toBeDefined();
    const html = msg.html!;
    expect(html).toContain("42");
    expect(html).toContain("50");          // next milestone
    expect(html).toContain("8 to go");
    expect(html).toContain("<h2>");        // native heading, not emoji-faked
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

describe("formatTaskDetail", () => {
  const detail = {
    name: "Ship feature <v2>",
    slug: "ship-feature-v2",
    status: "active",
    priority: 5,
    category: "work",
    due_date: "2026-06-15",
    tokens_on_completion: 10,
    created: "2026-06-01",
    google_event_id: "abc123",
    path: "40-tasks/active/ship-feature-v2.md",
    content: "# Ship feature <v2>\n\n## Description\nBig & important release\n\n## Checklist\n- [ ]\n\n## Notes\n",
  };

  it("escapes HTML in name and body", async () => {
    const { formatTaskDetail } = await import("../../src/formatters/telegram.js");
    const result = formatTaskDetail(detail as any);
    expect(result).toContain("Ship feature &lt;v2&gt;");
    expect(result).toContain("Big &amp; important release");
    expect(result).not.toContain("<v2>");
  });

  it("shows frontmatter fields", async () => {
    const { formatTaskDetail } = await import("../../src/formatters/telegram.js");
    const result = formatTaskDetail(detail as any);
    expect(result).toContain("Priority: <b>5</b>");
    expect(result).toContain("Category: work");
    expect(result).toContain("Due: 2026-06-15");
    expect(result).toContain("Tokens on completion: 10");
    expect(result).toContain("Synced to Google Calendar");
  });

  it("drops empty template sections but keeps written content", async () => {
    const { formatTaskDetail } = await import("../../src/formatters/telegram.js");
    const result = formatTaskDetail(detail as any);
    expect(result).toContain("## Description");
    expect(result).not.toContain("## Checklist");
    expect(result).not.toContain("## Notes");
  });

  it("omits the body block when content is pure boilerplate", async () => {
    const { formatTaskDetail } = await import("../../src/formatters/telegram.js");
    const result = formatTaskDetail({
      ...detail,
      content: "# Title\n\n## Description\n\n\n## Checklist\n- [ ]\n\n## Notes\n",
    } as any);
    expect(result).not.toContain("<blockquote>");
  });
});
