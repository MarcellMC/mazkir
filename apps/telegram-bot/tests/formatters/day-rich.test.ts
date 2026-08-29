import { describe, it, expect } from "vitest";
import { buildDayRich } from "../../src/formatters/day-rich.js";

const base = {
  date: "2026-08-29",
  tokens_today: 0,
  tokens_total: 0,
  blocks: [],
  gaps: [],
  coverage: { covered_minutes: 0, unaccounted_minutes: 0 },
  todos: [],
  notes: [],
};

function html(data: unknown): string {
  return buildDayRich(data as never).html ?? "";
}

describe("buildDayRich", () => {
  it("renders the date and coverage in the header", () => {
    const out = html({
      ...base,
      coverage: { covered_minutes: 155, unaccounted_minutes: 745 },
    });
    expect(out).toContain("29 Aug");
    expect(out).toContain("2.6h covered");
    expect(out).toContain("12.4h unaccounted");
  });

  it("renders blocks and gaps interleaved in time order", () => {
    const out = html({
      ...base,
      blocks: [
        { id: "a", start: "07:00", end: "07:40", title: "Dog walk", source: "habit",
          type: "habit", completed: false, activity: null, category: null,
          state: "suggested", habit_progress: "1/2" },
        { id: "b", start: "09:05", end: "10:00", title: "Standup", source: "calendar",
          type: "calendar", completed: false, activity: "meetings", category: "work",
          state: "suggested", habit_progress: null },
      ],
      gaps: [{ start: "07:40", end: "09:05", minutes: 85 }],
    });
    expect(out.indexOf("Dog walk")).toBeLessThan(out.indexOf("⚠"));
    expect(out.indexOf("⚠")).toBeLessThan(out.indexOf("Standup"));
    expect(out).toContain("1.4h");
  });

  it("shows the facet column only when populated", () => {
    const unclassified = html({
      ...base,
      blocks: [{ id: "a", start: "09:00", end: "10:00", title: "Standup",
                 source: "calendar", type: "calendar", completed: false,
                 activity: null, category: null, state: "suggested",
                 habit_progress: null }],
    });
    expect(unclassified).not.toContain("×");
    const classified = html({
      ...base,
      blocks: [{ id: "a", start: "09:00", end: "10:00", title: "Standup",
                 source: "calendar", type: "calendar", completed: false,
                 activity: "meetings", category: "work", state: "suggested",
                 habit_progress: null }],
    });
    expect(classified).toContain("meetings × work");
  });

  it("renders todos as native task list items", () => {
    const out = html({
      ...base,
      todos: [
        { text: "Order dog food", done: false, section: "Tasks",
          scheduled_at: null, duration_minutes: 30 },
        { text: "Walk dog", done: true, section: "Tasks",
          scheduled_at: null, duration_minutes: null },
      ],
    });
    expect(out).toContain('<input type="checkbox">Order dog food');
    expect(out).toContain('<input type="checkbox" checked>Walk dog');
  });

  it("omits timed todos, which the timeline already shows", () => {
    const out = html({
      ...base,
      blocks: [{ id: "a", start: "14:00", end: "15:00", title: "Visit dentist",
                 source: "daily-note", type: "task", completed: false,
                 activity: null, category: null, state: "suggested",
                 habit_progress: null }],
      todos: [{ text: "Visit dentist", done: false, section: "Tasks",
                scheduled_at: "14:00", duration_minutes: 60 }],
    });
    expect(out.match(/Visit dentist/g)).toHaveLength(1);
  });

  it("escapes user text", () => {
    const out = html({
      ...base,
      todos: [{ text: "Email <boss> about the R&D budget", done: false,
                section: "Tasks", scheduled_at: null, duration_minutes: null }],
    });
    expect(out).toContain("Email &lt;boss&gt; about the R&amp;D budget");
    expect(out).not.toContain("<boss>");
  });

  it("renders a week bar with the selected day styled primary", () => {
    const out = html({ ...base, date: "2026-08-29" });
    expect(out).toContain('data="day:2026-08-29"');
    expect(out).toContain('style="primary"');
    expect(out).toContain('data="day:today"');
    expect((out.match(/<tg-button type="callback_data" data="day:2026-/g) ?? []).length)
      .toBe(9);  // 7 week days + prev + next
  });

  it("says so when there is nothing to show", () => {
    expect(html(base)).toContain("no blocks");
  });

  it("tolerates a server that omits todos", () => {
    const { todos, ...withoutTodos } = base;
    expect(() => html(withoutTodos)).not.toThrow();
  });
});
