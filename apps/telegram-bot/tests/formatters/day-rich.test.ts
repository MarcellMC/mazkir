import type { DailyResponse, DailyBlock, DailyGap } from "@mazkir/shared-types";
import { describe, it, expect, afterEach, vi } from "vitest";
import { buildDayRich } from "../../src/formatters/day-rich.js";

const base = {
  date: "2026-08-29",
  tokens_today: 0,
  tokens_total: 0,
  blocks: [],
  gaps: [],
  // 1440 (a "past day") is the neutral default here: every pre-existing
  // test in this file predates the ahead-marker feature and expects plain
  // rows, and 1440 is the one elapsed_minutes value that marks nothing
  // ahead regardless of a block's start.
  coverage: { covered_minutes: 0, unaccounted_minutes: 0, elapsed_minutes: 1440, confirmed_minutes: 0, pending_minutes: 0, incomplete_minutes: undefined },
  incomplete: [],
  todos: [],
  notes: [],
};

function html(data: DailyResponse): string {
  return buildDayRich(data).html ?? "";
}

function s5block(over: Partial<DailyBlock> = {}): DailyBlock {
  return {
    id: "e1", start: "09:00", end: "10:00", title: "Standup",
    source: "calendar", type: "event", completed: false,
    activity: null, category: null, state: "pending", habit_progress: null,
    ...over,
  };
}

function s5gap(over: Partial<DailyGap> = {}): DailyGap {
  return { start: "13:00", end: "14:15", minutes: 75, proposal: null, ...over };
}

function s5day(over: Partial<DailyResponse> = {}): DailyResponse {
  return {
    date: "2026-09-10", tokens_today: 0, tokens_total: 0,
    blocks: [], gaps: [], incomplete: [], todos: [], notes: [],
    coverage: {
      covered_minutes: 120, unaccounted_minutes: 60, elapsed_minutes: 720,
      confirmed_minutes: 60, pending_minutes: 60,
    },
    ...over,
  } as DailyResponse;
}

describe("Ship 5 glyphs", () => {
  it("marks a confirmed block with ✓ and gives it no buttons", () => {
    const html_str = html(s5day({ blocks: [s5block({ state: "approved" })] }));
    expect(html_str).toContain("✓ 09:00–10:00");
    expect(html_str).not.toMatch(/data="block:/);
  });

  it("marks a pending elapsed block with ● and three buttons", () => {
    const html_str = html(s5day({ blocks: [s5block()] }));
    expect(html_str).toContain("● 09:00–10:00");
    expect(html_str).toMatch(/data="block:approve:2026-09-10:e1"/);
    expect(html_str).toMatch(/data="block:dismiss:2026-09-10:e1"/);
    expect(html_str).toMatch(/data="block:edit:2026-09-10:e1"/);
  });

  it("marks a still-ahead block with ◌ and gives it no buttons", () => {
    const html_str = html(s5day({
      blocks: [s5block({ id: "e9", start: "19:00", end: "20:00" })],
    }));
    expect(html_str).toContain("◌ 19:00–20:00");
    expect(html_str).not.toMatch(/data="block:approve:2026-09-10:e9"/);
  });

  it("marks a gap with ░", () => {
    const html_str = html(s5day({ gaps: [s5gap()] }));
    expect(html_str).toContain("░ 13:00–14:15");
  });

  it("never renders ✅, ⚠ or ⟳ anywhere", () => {
    const html_str = html(s5day({
      blocks: [
        s5block({ state: "approved", completed: true }),
        s5block({ id: "e2", start: "21:00", end: "22:00" }),
      ],
      gaps: [s5gap()],
    }));
    for (const glyph of ["✅", "⚠", "⟳"]) expect(html_str).not.toContain(glyph);
  });

  it("folds completion into ✓ rather than adding a second marker", () => {
    const html_str = html(s5day({
      blocks: [s5block({ state: "approved", completed: true })],
    }));
    expect(html_str).toContain("✓ 09:00–10:00");
  });
});

describe("buttons live inside table cells", () => {
  it("wraps every block button row in a <td>", () => {
    // A top-level row stretches full width and an <li> hoists it out; only a
    // cell gives compact pills. Assert the containment, not just presence.
    const html_str = html(s5day({ blocks: [s5block()] }));
    expect(html_str).toMatch(/<td><tg-button-row>[\s\S]*?<\/tg-button-row><\/td>/);
  });
});

describe("gap proposals", () => {
  it("renders a proposal as a named row with the full control set", () => {
    const html_str = html(s5day({
      gaps: [s5gap({
        start: "00:20", end: "06:40", minutes: 380,
        proposal: { name: "Sleep", days_seen: 11 },
      })],
    }));
    expect(html_str).toContain("Sleep");
    expect(html_str).toContain("11/14");
    expect(html_str).toMatch(/data="prop:approve:2026-09-10:20:400"/);
    expect(html_str).toMatch(/data="prop:dismiss:2026-09-10:20:400"/);
  });

  it("renders an unproposed gap with a fill button carrying the duration", () => {
    const html_str = html(s5day({ gaps: [s5gap()] }));
    // hours() is (minutes / 60).toFixed(1), so a 75-minute gap reads 1.3h.
    // The brief said 1.2h, which was wrong — it was copied from a prototype
    // label that had been hand-written rather than computed.
    expect(html_str).toContain("+ 1.3h");
    expect(html_str).toMatch(/data="gap:fill:2026-09-10:780:855"/);
  });
});

describe("summary row and refresh", () => {
  it("keeps the h2 and puts coverage in a sub beside a right-aligned refresh", () => {
    const html_str = html(s5day());
    expect(html_str).toContain("<h2>");
    expect(html_str).toMatch(/<sub>[^<]*1\.0h confirmed[^<]*<\/sub>/);
    expect(html_str).toMatch(
      /<td align="right"><tg-button-row><tg-button[^>]*data="day:refresh:2026-09-10"/,
    );
  });
});

describe("the now divider", () => {
  it("is a centred subscript run of twelve middle dots either side", () => {
    const html_str = html(s5day({
      blocks: [
        s5block({ id: "past", state: "approved" }),
        s5block({ id: "future", start: "19:00", end: "20:00" }),
      ],
    }));
    expect(html_str).toContain(
      '<table><tr><td align="center"><sub>' +
      "·".repeat(12) + " now " + "·".repeat(12) +
      "</sub></td></tr></table>",
    );
  });

  it("is suppressed when one side is empty", () => {
    const html_str = html(s5day({
      blocks: [s5block({ state: "approved" })],
    }));
    expect(html_str).not.toContain(" now ");
  });
});

describe("approve all", () => {
  it("carries the count of what it will act on", () => {
    const html_str = html(s5day({
      blocks: [s5block(), s5block({ id: "e2", start: "10:00", end: "11:00" })],
      gaps: [s5gap({ proposal: { name: "Sleep", days_seen: 11 } })],
    }));
    // Two pending elapsed blocks plus one proposal. The number is in the
    // label deliberately: approve-all banks guesses, so it must not hide how
    // many things it touches behind the word "all".
    expect(html_str).toContain("approve all 3");
    expect(html_str).toMatch(/data="day:approveall:2026-09-10"/);
  });

  it("is absent when there is nothing to approve", () => {
    const html_str = html(s5day({
      blocks: [s5block({ state: "approved" })],
    }));
    expect(html_str).not.toContain("approve all");
  });
});

describe("the tail", () => {
  it("has one rule before both week and nav bars (hr groups all nav)", () => {
    const html_str = html(s5day());
    expect((html_str.match(/<hr>/g) ?? []).length).toBe(1);
    const rule = html_str.indexOf("<p>&nbsp;</p><hr>");
    expect(html_str.indexOf('data="day:2026-09-06"')).toBeGreaterThan(rule);
    expect(html_str.indexOf('data="day:today"')).toBeGreaterThan(rule);
  });
});

describe("buildDayRich", () => {
  it("renders the date and coverage in the header", () => {
    const out = html({
      ...base,
      coverage: { covered_minutes: 0, unaccounted_minutes: 745, elapsed_minutes: 1440, confirmed_minutes: 155, pending_minutes: 0, incomplete_minutes: undefined },
    });
    expect(out).toContain("29 Aug");
    expect(out).toContain("2.6h confirmed");
    expect(out).toContain("12.4h unaccounted");
  });

  it("renders blocks and gaps interleaved in time order", () => {
    const out = html({
      ...base,
      blocks: [
        { id: "a", start: "07:00", end: "07:40", title: "Dog walk", source: "habit",
          type: "habit", completed: false, activity: null, category: null,
          state: "pending", habit_progress: "1/2" },
        { id: "b", start: "09:05", end: "10:00", title: "Standup", source: "calendar",
          type: "calendar", completed: false, activity: "meetings", category: "work",
          state: "pending", habit_progress: null },
      ],
      gaps: [{ start: "07:40", end: "09:05", minutes: 85, proposal: null }],
    });
    expect(out.indexOf("Dog walk")).toBeLessThan(out.indexOf("░"));
    expect(out.indexOf("░")).toBeLessThan(out.indexOf("Standup"));
    expect(out).toContain("1.4h");
  });

  it("shows the facet column only when populated", () => {
    const unclassified = html({
      ...base,
      blocks: [{ id: "a", start: "09:00", end: "10:00", title: "Standup",
                 source: "calendar", type: "calendar", completed: false,
                 activity: null, category: null, state: "approved",
                 habit_progress: null }],
    });
    expect(unclassified).not.toContain("×");
    const classified = html({
      ...base,
      blocks: [{ id: "a", start: "09:00", end: "10:00", title: "Standup",
                 source: "calendar", type: "calendar", completed: false,
                 activity: "meetings", category: "work", state: "approved",
                 habit_progress: null }],
    });
    expect(classified).toContain("meetings × work");
  });

  it("renders a lone activity when category is unset", () => {
    const out = html({
      ...base,
      blocks: [{ id: "a", start: "09:00", end: "10:00", title: "Standup",
                 source: "calendar", type: "calendar", completed: false,
                 activity: "meetings", category: null, state: "approved",
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
                 activity: null, category: "work", state: "approved",
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
                 activity: null, category: null, state: "pending",
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

  it("renders a week bar with the selected day styled success", () => {
    const out = html({ ...base, date: "2026-08-29" });
    expect(out).toContain('data="day:2026-08-29"');
    expect(out).toContain('style="success"');
    expect(out).toContain('data="day:today"');
    expect((out.match(/<tg-button type="callback_data" data="day:2026-/g) ?? []).length)
      .toBe(9);  // 7 week days + prev + next
  });

  describe("the week bar (fixed Sunday->Saturday)", () => {
    // 2026-08-23 (Sun) .. 2026-08-29 (Sat) is one full week, entirely
    // within August, used as the reference week for most of these tests.
    const HEBREW_WEEK: [string, string][] = [
      ["2026-08-23", "א"], // Sun
      ["2026-08-24", "ב"], // Mon
      ["2026-08-25", "ג"], // Tue
      ["2026-08-26", "ד"], // Wed
      ["2026-08-27", "ה"], // Thu
      ["2026-08-28", "ו"], // Fri
      ["2026-08-29", "ש"], // Sat
    ];

    // Invisible-character constants, pinned by codepoint rather than by
    // pasting the glyph — see the comment above their definitions in
    // day-rich.ts for what each does and why the isolate/separator choice
    // matters.
    const LRI = "⁦";
    const PDI = "⁩";
    const HYPHENATION_POINT = "‧";

    /** Build the expected two-line label for a given day-of-month + Hebrew
     *  letter, matching the LRI/date/separator/letter/PDI shape produced by
     *  weekBar(). */
    function expectedLabel(icon: string, day: number, letter: string): string {
      return `${icon}\n${LRI}${day}${HYPHENATION_POINT}${letter}${PDI}`;
    }

    /** Pull the 7 weekday buttons out of the rendered HTML, in document
     *  order, distinguishing them from the `‹`/`›`/`today` nav buttons by
     *  label (the nav buttons never contain a newline). The label can
     *  contain `<` as part of user-invisible bidi marks, but never a literal
     *  `<` character, so matching up to `</tg-button>` non-greedily is safe. */
    function weekdayButtons(out: string): { date: string; label: string; selected: boolean }[] {
      const re = /<tg-button type="callback_data" data="day:(\d{4}-\d{2}-\d{2})"( style="success")?>([\s\S]*?)<\/tg-button>/g;
      const found: { date: string; label: string; selected: boolean }[] = [];
      for (const m of out.matchAll(re)) {
        const label = m[3]!;
        if (!label.includes("\n")) continue; // nav buttons (‹, ›, today) are single-line
        found.push({ date: m[1]!, label, selected: Boolean(m[2]) });
      }
      return found;
    }

    it("always orders the seven buttons Sunday->Saturday, regardless of which weekday is selected", () => {
      const wed = weekdayButtons(html({ ...base, date: "2026-08-26" }));
      const sat = weekdayButtons(html({ ...base, date: "2026-08-29" }));
      const expectedDates = HEBREW_WEEK.map(([d]) => d);
      expect(wed.map((b) => b.date)).toEqual(expectedDates);
      expect(sat.map((b) => b.date)).toEqual(expectedDates);
    });

    it("maps the Hebrew letters to the correct weekdays", () => {
      const out = html({ ...base, date: "2026-08-26" });
      const buttons = weekdayButtons(out);
      for (const [date, letter] of HEBREW_WEEK) {
        const button = buttons.find((b) => b.date === date)!;
        expect(button.label).toContain(`${HYPHENATION_POINT}${letter}${PDI}`);
      }
    });

    it("places the correct icon at each position, independent of which day is selected", () => {
      // Two different selected dates, so a passing assertion proves the icon
      // is a function of position, not of selection.
      for (const selected of ["2026-08-23", "2026-08-27"]) {
        const buttons = weekdayButtons(html({ ...base, date: selected }));
        expect(buttons.find((b) => b.date === "2026-08-23")!.label.startsWith("♦️\n")).toBe(true); // Sun
        expect(buttons.find((b) => b.date === "2026-08-29")!.label.startsWith("🕯\n")).toBe(true); // Sat
        expect(buttons.find((b) => b.date === "2026-08-28")!.label.startsWith("💠\n")).toBe(true); // Fri
        const mondayToThursday = ["2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27"];
        for (const date of mondayToThursday) {
          expect(buttons.find((b) => b.date === date)!.label.startsWith("🔸\n")).toBe(true);
        }
        // Exactly one of each of the singleton icons, and exactly four 🔸s.
        expect(buttons.filter((b) => b.label.startsWith("♦️\n"))).toHaveLength(1);
        expect(buttons.filter((b) => b.label.startsWith("🔸\n"))).toHaveLength(4);
        expect(buttons.filter((b) => b.label.startsWith("💠\n"))).toHaveLength(1);
        expect(buttons.filter((b) => b.label.startsWith("🕯\n"))).toHaveLength(1);
      }
    });

    it("joins the icon and the date+letter line with a literal newline", () => {
      const out = html({ ...base, date: "2026-08-26" });
      const buttons = weekdayButtons(out);
      const sunday = buttons.find((b) => b.date === "2026-08-23")!;
      expect(sunday.label).toBe(expectedLabel("♦️", 23, "א"));
    });

    it("isolates the label so the date renders left of the Hebrew letter", () => {
      // Hebrew is strong RTL: without the isolate, "30‧א" displays as
      // "א‧30". These characters are invisible — assert on codepoints so a
      // future edit cannot silently drop them.
      const out = html({ ...base, date: "2026-08-30" });
      expect(out).toContain(`${LRI}30${HYPHENATION_POINT}א${PDI}`);
    });

    it("separates date from letter with a hyphenation point, not a middot or hyphen", () => {
      // Scoped to the week-bar button labels, not the whole render: the
      // header's "· today" suffix (headerLabel, a separate feature) uses the
      // ASCII middot U+00B7 legitimately when the rendered date happens to
      // be the real "today" — that is not the character under test here.
      const out = html({ ...base, date: "2026-08-30" });
      const buttons = weekdayButtons(out);
      for (const b of buttons) {
        expect(b.label).toContain(HYPHENATION_POINT);
        expect(b.label).not.toContain("·"); // middot
        expect(b.label).not.toContain("-א"); // ASCII hyphen + alef
      }
    });

    it("marks the selected day, and only the selected day, success", () => {
      const out = html({ ...base, date: "2026-08-26" });
      const buttons = weekdayButtons(out);
      const selected = buttons.filter((b) => b.selected);
      expect(selected).toHaveLength(1);
      expect(selected[0]!.date).toBe("2026-08-26");
    });

    it("marks the selected day success even when it is Saturday", () => {
      const out = html({ ...base, date: "2026-08-29" });
      const buttons = weekdayButtons(out);
      const selected = buttons.filter((b) => b.selected);
      expect(selected).toHaveLength(1);
      expect(selected[0]!.date).toBe("2026-08-29");
    });

    it("pages the arrows by a full week, not by one day", () => {
      const out = html({ ...base, date: "2026-08-26" });
      expect(out).toContain('data="day:2026-08-19">‹</tg-button>');
      expect(out).toContain('data="day:2026-09-02">›</tg-button>');
    });

    it("shows the selected Sunday first when a Sunday is selected", () => {
      const out = html({ ...base, date: "2026-08-23" });
      const buttons = weekdayButtons(out);
      expect(buttons[0]!.date).toBe("2026-08-23");
      expect(buttons[0]!.selected).toBe(true);
      expect(buttons[buttons.length - 1]!.date).toBe("2026-08-29");
    });

    it("shows the selected Saturday last, with the same week's Sunday first", () => {
      const out = html({ ...base, date: "2026-08-29" });
      const buttons = weekdayButtons(out);
      expect(buttons[0]!.date).toBe("2026-08-23");
      expect(buttons[buttons.length - 1]!.date).toBe("2026-08-29");
      expect(buttons[buttons.length - 1]!.selected).toBe(true);
    });

    it("renders a week spanning a month boundary correctly", () => {
      // The week containing 2026-08-31 (Mon) runs Sun 2026-08-30 through
      // Sat 2026-09-05 — it crosses from August into September.
      const out = html({ ...base, date: "2026-08-31" });
      const buttons = weekdayButtons(out);
      expect(buttons.map((b) => b.date)).toEqual([
        "2026-08-30", "2026-08-31", "2026-09-01", "2026-09-02",
        "2026-09-03", "2026-09-04", "2026-09-05",
      ]);
      expect(buttons[0]!.label).toBe(expectedLabel("♦️", 30, "א"));
      expect(buttons[1]!.label).toBe(expectedLabel("🔸", 31, "ב"));
      expect(buttons[1]!.selected).toBe(true);
      expect(buttons[2]!.label).toBe(expectedLabel("🔸", 1, "ג"));
      expect(buttons[6]!.label).toBe(expectedLabel("🕯", 5, "ש"));
    });
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
      activity: null, category: null, state: "approved", habit_progress: null,
    };

    it("marks a completed block", () => {
      // `/day` filters timed todos out of the Todos list because they are
      // already blocks, so without this a checked `- [x] 14:00 - Standup`
      // rendered identically to an outstanding one and appeared nowhere
      // else. Ship 1 rendered it as done.
      const out = html({ ...base, blocks: [doneBlock] });
      expect(out).toContain("<td>\u2713 14:00\u201315:00</td>");
    });

    it("leaves an outstanding block unmarked", () => {
      const out = html({ ...base, blocks: [{ ...doneBlock, completed: false, state: "pending" }] });
      expect(out).toContain("\u25cf 14:00\u201315:00");
    });

    it("keeps the completion marker out of the habit_progress column", () => {
      // A completed habit has both signals, and they must not collide:
      // completion is folded into the state glyph.
      const out = html({
        ...base,
        blocks: [{ ...doneBlock, title: "Dog walk", source: "habit",
                   type: "habit", habit_progress: "2/2" }],
      });
      expect(out).toContain("<td>\u2713 14:00\u201315:00</td>");
      expect(out).toContain("<td>2/2</td>");
    });
  });

  describe("the now-divider and ahead marker", () => {
    const block = (start: string, end: string, title: string, state: "pending" | "approved" = "pending") => ({
      id: title, start, end, title, source: "calendar", type: "calendar",
      completed: false, activity: null, category: null, state,
      habit_progress: null,
    });

    // The labelled divider's exact text, built the same way day-rich.ts
    // builds it (U+00B7 middle dot, twelve either side of " now "), so a future
    // edit that quietly swaps in hyphens or other dots fails this rather than passing silently.
    const NOW_DIVIDER_HTML = `<table><tr><td align="center"><sub>${"\u00b7".repeat(12)} now ${"\u00b7".repeat(12)}</sub></td></tr></table>`;

    it("today with rows on both sides: exactly one <hr> (the spacer), the labelled divider, four <table>s, \u25cc on ahead blocks only", () => {
      const out = html({
        ...base,
        coverage: { covered_minutes: 0, unaccounted_minutes: 0, elapsed_minutes: 600, confirmed_minutes: 0, pending_minutes: 0, incomplete_minutes: undefined }, // 10:00
        blocks: [block("09:00", "09:30", "Past thing"), block("11:00", "12:00", "Future thing")],
      });
      expect((out.match(/<table>/g) ?? []).length).toBe(4);
      // Only the week-bar/nav spacer's <hr> remains; the now-divider is no
      // longer an <hr> at all.
      expect((out.match(/<hr>/g) ?? []).length).toBe(1);
      expect(out).toContain(NOW_DIVIDER_HTML);
      // Order: elapsed table -> now-divider -> ahead table -> spacer
      const firstTableEnd = out.indexOf("</table>");
      const dividerAt = out.indexOf(NOW_DIVIDER_HTML);
      const lastTableEnd = out.lastIndexOf("</table>");
      const spacerAt = out.indexOf("<p>&nbsp;</p><hr>");
      expect(firstTableEnd).toBeLessThan(dividerAt);
      expect(dividerAt).toBeLessThan(lastTableEnd);
      expect(lastTableEnd).toBeLessThan(spacerAt);
      expect(out.indexOf("Past thing")).toBeLessThan(out.indexOf("Future thing"));
      expect(out).not.toContain("\u25cc 09:00");
      expect(out).toContain("\u25cc 11:00");
    });

    it("pins the divider's exact middle-dot string, not hyphens", () => {
      const out = html({
        ...base,
        coverage: { covered_minutes: 0, unaccounted_minutes: 0, elapsed_minutes: 600 },
        blocks: [block("09:00", "09:30", "Past thing"), block("11:00", "12:00", "Future thing")],
      });
      expect(out).toContain(NOW_DIVIDER_HTML);
      expect(out).not.toContain("-------- now --------");
    });

    it("today with everything elapsed: exactly one <hr> (spacer only), no labelled divider, two tables (summary + blocks), no \u25cc", () => {
      const out = html({
        ...base,
        coverage: { covered_minutes: 30, unaccounted_minutes: 1170, elapsed_minutes: 1200, confirmed_minutes: 30, pending_minutes: 0, incomplete_minutes: undefined },
        blocks: [block("09:00", "09:30", "Past thing")],
      });
      expect((out.match(/<hr>/g) ?? []).length).toBe(1);
      expect(out).not.toContain(NOW_DIVIDER_HTML);
      expect((out.match(/<table>/g) ?? []).length).toBe(2);
      expect(out).not.toContain("\u25cc");
    });

    it("today with everything ahead: exactly one <hr> (spacer only), no labelled divider, two tables (summary + blocks), \u25cc present", () => {
      const out = html({
        ...base,
        coverage: { covered_minutes: 0, unaccounted_minutes: 0, elapsed_minutes: 60, confirmed_minutes: 0, pending_minutes: 0, incomplete_minutes: undefined },
        blocks: [block("09:00", "09:30", "Future thing")],
      });
      expect((out.match(/<hr>/g) ?? []).length).toBe(1);
      expect(out).not.toContain(NOW_DIVIDER_HTML);
      expect((out.match(/<table>/g) ?? []).length).toBe(2);
      expect(out).toContain("\u25cc 09:00");
    });

    it("a past day (elapsed_minutes: 1440): exactly one <hr> (spacer only), no labelled divider, no \u25cc", () => {
      const out = html({
        ...base,
        coverage: { covered_minutes: 30, unaccounted_minutes: 1410, elapsed_minutes: 1440 },
        blocks: [block("09:00", "09:30", "Old thing")],
      });
      expect((out.match(/<hr>/g) ?? []).length).toBe(1);
      expect(out).not.toContain(NOW_DIVIDER_HTML);
      expect(out).not.toContain("\u25cc");
    });

    it("a future day (elapsed_minutes: 0): exactly one <hr> (spacer only), no labelled divider; every block is ahead, so \u25cc on all of them", () => {
      const out = html({
        ...base,
        coverage: { covered_minutes: 0, unaccounted_minutes: 0, elapsed_minutes: 0 },
        blocks: [block("09:00", "09:30", "Thing A"), block("14:00", "15:00", "Thing B")],
      });
      expect((out.match(/<hr>/g) ?? []).length).toBe(1);
      expect(out).not.toContain(NOW_DIVIDER_HTML);
      expect(out).toContain("\u25cc 09:00");
      expect(out).toContain("\u25cc 14:00");
    });

    it("suppresses the labelled divider on today with no rows at all, same rule as an empty side", () => {
      // The existing elapsed-only / ahead-only cases above already prove
      // suppression when one side is empty; this covers the other edge the
      // suppression rule has to hold for \u2014 today, but nothing to show at
      // all \u2014 which the old <hr>-counting tests never exercised on its own.
      const out = html({
        ...base,
        coverage: { covered_minutes: 0, unaccounted_minutes: 0, elapsed_minutes: 600 },
        blocks: [],
      });
      expect(out).not.toContain(NOW_DIVIDER_HTML);
      expect((out.match(/<hr>/g) ?? []).length).toBe(1);
    });

    it("a gap row in the ahead section never carries \u25cc", () => {
      const out = html({
        ...base,
        coverage: { covered_minutes: 0, unaccounted_minutes: 0, elapsed_minutes: 600 },
        blocks: [block("11:00", "12:00", "Future thing")],
        gaps: [{ start: "12:00", end: "13:00", minutes: 60, proposal: null }],
      });
      // Exactly one `\u25cc` in the whole render \u2014 the block's, never the gap's.
      expect((out.match(/\u25cc/g) ?? []).length).toBe(1);
      expect(out).toContain("\u2591 12:00");
    });

    it("an approved block that is somehow ahead renders \u25cc, not \u2713", () => {
      const out = html({
        ...base,
        coverage: { covered_minutes: 0, unaccounted_minutes: 0, elapsed_minutes: 600 },
        blocks: [block("11:00", "12:00", "Weirdly approved early", "approved")],
      });
      expect(out).toContain("\u25cc 11:00");
      expect(out).not.toContain("\u2713");
    });
  });

  it("separates the week bar from the navigation row", () => {
    // A plain space collapses and the gap disappears \u2014 assert the entity
    // specifically, not just "some whitespace".
    const out = html({ ...base, date: "2026-08-30" });
    expect(out).toContain("<p>&nbsp;</p><hr>");
  });

  it("puts the spacer before the week bar (one rule groups all nav)", () => {
    const out = html({ ...base, date: "2026-08-30" });
    const weekBarAt = out.indexOf('data="day:2026-08-30"');
    const spacerAt = out.indexOf("<p>&nbsp;</p><hr>");
    const navAt = out.indexOf('data="day:today"');
    expect(spacerAt).toBeLessThan(weekBarAt);
    expect(weekBarAt).toBeLessThan(navAt);
  });
});

describe("incomplete blocks", () => {
  it("renders a needs-a-time section", () => {
    const out = html({
      ...base,
      incomplete: [
        { id: "e1", title: "Dog walk", start: null, end: "16:40",
          missing: ["start_time"], source: "manual" },
      ],
    });
    expect(out).toContain("Needs a time");
    expect(out).toContain("Dog walk");
    expect(out).toContain("16:40");
  });

  it("omits the section entirely when there are none", () => {
    expect(html({ ...base, incomplete: [] })).not.toContain("Needs a time");
  });

  it("survives a payload with no incomplete field at all", () => {
    // `base` predates this feature and has no `incomplete` key, which is
    // exactly the shape an older server sends.
    expect(html(base)).not.toContain("Needs a time");
  });

  it("escapes the title", () => {
    const out = html({
      ...base,
      incomplete: [
        { id: "e1", title: "Dog & <walk>", start: null, end: "16:40",
          missing: ["start_time"], source: "manual" },
      ],
    });
    expect(out).toContain("Dog &amp; &lt;walk&gt;");
  });
});
