import { describe, it, expect, afterEach, vi } from "vitest";
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

  it("renders a lone activity when category is unset", () => {
    const out = html({
      ...base,
      blocks: [{ id: "a", start: "09:00", end: "10:00", title: "Standup",
                 source: "calendar", type: "calendar", completed: false,
                 activity: "meetings", category: null, state: "suggested",
                 habit_progress: null }],
    });
    expect(out).toContain("<td>meetings</td>");
    expect(out).not.toContain("×");
  });

  it("renders a lone category when activity is unset", () => {
    const out = html({
      ...base,
      blocks: [{ id: "a", start: "09:00", end: "10:00", title: "Standup",
                 source: "calendar", type: "calendar", completed: false,
                 activity: null, category: "work", state: "suggested",
                 habit_progress: null }],
    });
    expect(out).toContain("<td>work</td>");
    expect(out).not.toContain("×");
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

  it("labels the todos and notes lists so they read as two sections, not one", () => {
    const out = html({
      ...base,
      todos: [{ text: "Order dog food", done: false, section: "Tasks",
                scheduled_at: null, duration_minutes: null }],
      notes: [{ text: "Slept badly" }],
    });
    expect(out).toContain("Todos");
    expect(out).toContain("Notes");
    // The heading has to precede its own list, not just appear somewhere.
    const todosHeading = out.indexOf("Todos");
    const todosItem = out.indexOf("Order dog food");
    const notesHeading = out.indexOf("Notes");
    const notesItem = out.indexOf("Slept badly");
    expect(todosHeading).toBeLessThan(todosItem);
    expect(notesHeading).toBeLessThan(notesItem);
    expect(todosItem).toBeLessThan(notesHeading);
  });

  describe("today, in the vault's timezone rather than UTC", () => {
    afterEach(() => {
      vi.useRealTimers();
    });

    it("still says today just after local midnight, while UTC is still on the previous date", () => {
      // 2026-08-29T21:30:00Z is 2026-08-30 00:30 in Asia/Jerusalem (UTC+3
      // in August). A UTC-based "today" would compute 2026-08-29 here and
      // silently drop the "today" suffix from a page that is today.
      vi.useFakeTimers();
      vi.setSystemTime(new Date("2026-08-29T21:30:00Z"));
      const out = html({ ...base, date: "2026-08-30" });
      // Assert on the HEADER, not on the string "today" anywhere in the
      // output: navBar unconditionally emits `data="day:today"` into every
      // render, so `toContain("today")` was true for every input and stayed
      // green with the UTC bug restored.
      expect(out).toContain("<h2>Sun 30 Aug \u00b7 today</h2>");
    });

    it("does not call another date today", () => {
      // The negative control the vacuous assertion could never provide.
      vi.useFakeTimers();
      vi.setSystemTime(new Date("2026-08-29T21:30:00Z"));
      const out = html({ ...base, date: "2026-09-05" });
      expect(out).toContain("<h2>Sat 5 Sept</h2>");
      expect(out).not.toContain("\u00b7 today");
    });
  });

  describe("completion", () => {
    const doneBlock = {
      id: "a", start: "14:00", end: "15:00", title: "Standup",
      source: "daily-note", type: "task", completed: true,
      activity: null, category: null, state: "suggested", habit_progress: null,
    };

    it("marks a completed block", () => {
      // `/day` filters timed todos out of the Todos list because they are
      // already blocks, so without this a checked `- [x] 14:00 - Standup`
      // rendered identically to an outstanding one and appeared nowhere
      // else. Ship 1 rendered it as done.
      const out = html({ ...base, blocks: [doneBlock] });
      expect(out).toContain("<td>\u2705 14:00\u201315:00</td>");
    });

    it("leaves an outstanding block unmarked", () => {
      const out = html({ ...base, blocks: [{ ...doneBlock, completed: false }] });
      expect(out).toContain("<td>14:00\u201315:00</td>");
      expect(out).not.toContain("\u2705");
    });

    it("keeps the completion marker out of the habit_progress column", () => {
      // A completed habit has both signals, and they must not collide:
      // completion prefixes the time cell, progress owns the marker cell.
      const out = html({
        ...base,
        blocks: [{ ...doneBlock, title: "Dog walk", source: "habit",
                   type: "habit", habit_progress: "2/2" }],
      });
      expect(out).toContain("<td>\u2705 14:00\u201315:00</td>");
      expect(out).toContain("<td>2/2</td>");
    });
  });
});
