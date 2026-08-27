import { describe, it, expect } from "vitest";
import {
  formatDay,
  formatTasks,
  formatHabits,
  formatGoals,
  formatGoalDetail,
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

  it("numbers goals so they line up with the inline keyboard buttons", () => {
    const result = formatGoals([
      { name: "Get fit", status: "in-progress", priority: "high", progress: 30 },
      { name: "Learn Python", status: "not-started", priority: "medium", progress: 0 },
    ]);
    expect(result).toContain("1. Get fit");
    expect(result).toContain("2. Learn Python");
  });

  it("maps the vault's string priorities onto the emoji scale", () => {
    const high = formatGoals([{ name: "A", status: "active", priority: "high", progress: 0 }]);
    const low = formatGoals([{ name: "B", status: "active", priority: "low", progress: 0 }]);
    expect(high).toContain("🔴");
    expect(low).toContain("🟢");
  });

  it("escapes HTML in goal names", () => {
    const result = formatGoals([
      { name: "Ship <b>v2</b>", status: "active", priority: "high", progress: 0 },
    ]);
    expect(result).toContain("Ship &lt;b&gt;v2&lt;/b&gt;");
  });
});

describe("formatGoalDetail", () => {
  const GOAL = {
    name: "Get fit",
    slug: "get-fit",
    status: "in-progress",
    priority: "high",
    progress: 30,
    start_date: "2026-01-01",
    target_date: "2026-12-31",
    category: "health",
    path: "30-goals/2026/get-fit.md",
    content: "# Get fit\n\n## Why\nBecause stairs.\n\n## Notes\n",
  };

  it("renders progress, priority, status and dates", () => {
    const result = formatGoalDetail(GOAL);
    expect(result).toContain("Get fit");
    expect(result).toContain("30%");
    expect(result).toContain("high");
    expect(result).toContain("in-progress");
    expect(result).toContain("health");
    expect(result).toContain("2026-12-31");
  });

  it("includes the note body but drops the title and empty sections", () => {
    const result = formatGoalDetail(GOAL);
    expect(result).toContain("Because stairs.");
    expect(result).not.toContain("# Get fit");
    expect(result).not.toContain("## Notes");
  });

  it("lists string milestones and ignores richer entries", () => {
    const result = formatGoalDetail({
      ...GOAL,
      milestones: ["Run 5k", { name: "Run 10k" }] as unknown as string[],
    });
    expect(result).toContain("• Run 5k");
    expect(result).not.toContain("object Object");
  });

  it("omits the milestones block when there are none", () => {
    expect(formatGoalDetail({ ...GOAL, milestones: [] })).not.toContain("Milestones");
  });

  it("escapes HTML in the name and body", () => {
    const result = formatGoalDetail({
      ...GOAL,
      name: "Ship <v2>",
      content: "## Why\n<script>alert(1)</script>",
    });
    expect(result).toContain("Ship &lt;v2&gt;");
    expect(result).not.toContain("<script>");
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

describe("formatDay todos", () => {
  const base = {
    date: "2026-08-20",
    tokens_today: 0,
    tokens_total: 0,
    schedule: [],
    notes: [],
  };

  it("lists untimed todos", () => {
    const out = formatDay({
      ...base,
      todos: [
        { text: "Order dog food", done: false, section: "Tasks",
          scheduled_at: null, duration_minutes: 30 },
      ],
    } as never);
    expect(out).toContain("Order dog food");
    expect(out).toContain("30m");
  });

  it("marks done todos", () => {
    const out = formatDay({
      ...base,
      todos: [
        { text: "Walk dog", done: true, section: "Tasks",
          scheduled_at: null, duration_minutes: null },
      ],
    } as never);
    expect(out).toContain("☑️ Walk dog");
  });

  it("omits timed todos, which the schedule already shows", () => {
    const out = formatDay({
      ...base,
      schedule: [{ start: "14:00", title: "Visit dentist",
                   source: "daily-task", completed: false }],
      todos: [
        { text: "Visit dentist", done: false, section: "Tasks",
          scheduled_at: "14:00", duration_minutes: 60 },
      ],
    } as never);
    expect(out.match(/Visit dentist/g)).toHaveLength(1);
  });

  it("renders no todo block when there are none", () => {
    const out = formatDay({ ...base, todos: [] } as never);
    expect(out).not.toContain("Todos");
    // Not just the header — an item rendered without one would still be wrong.
    expect(out).not.toContain("\u2610");
  });

  it("separates notes from todos when there is no schedule", () => {
    const out = formatDay({
      ...base,
      todos: [
        { text: "Order dog food", done: false, section: "Tasks",
          scheduled_at: null, duration_minutes: null },
      ],
      notes: [{ text: "Slept badly" }],
    } as never);
    expect(out).toContain("Order dog food\n\n\uD83D\uDCDD <b>Notes</b>");
  });

  it("escapes HTML in todo text", () => {
    // Telegram rejects the whole message on a stray tag, and /day's catch
    // misreports that as the server being down.
    const out = formatDay({
      ...base,
      todos: [
        { text: "Email <boss> about the R&D budget", done: false,
          section: "Tasks", scheduled_at: null, duration_minutes: null },
      ],
    } as never);
    expect(out).toContain("Email &lt;boss&gt; about the R&amp;D budget");
    expect(out).not.toContain("<boss>");
  });

  it("escapes HTML in schedule titles and note text", () => {
    const out = formatDay({
      ...base,
      schedule: [{ start: "09:00", title: "Standup <eng>",
                   source: "calendar", completed: false }],
      notes: [{ text: "spend < 500 & rising" }],
      todos: [],
    } as never);
    expect(out).toContain("Standup &lt;eng&gt;");
    expect(out).toContain("spend &lt; 500 &amp; rising");
  });

  it("renders a zero-minute duration rather than dropping it", () => {
    const out = formatDay({
      ...base,
      todos: [
        { text: "Quick win", done: false, section: "Tasks",
          scheduled_at: null, duration_minutes: 0 },
      ],
    } as never);
    expect(out).toContain("(0m)");
  });
});
