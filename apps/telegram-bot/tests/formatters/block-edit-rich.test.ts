import { describe, it, expect } from "vitest";
import { buildBlockEditRich, NUDGES } from "../../src/formatters/block-edit-rich.js";
import type { DailyBlock } from "@mazkir/shared-types";

const block: DailyBlock = {
  id: "e1", start: "09:05", end: "10:00", title: "Standup",
  source: "calendar", type: "event", completed: false,
  activity: null, category: null, state: "pending", habit_progress: null,
};

describe("the nudge pad", () => {
  it("offers 30, 15 and 5 minute steps, largest first", () => {
    expect(NUDGES).toEqual([30, 15, 5]);
  });

  it("puts the minus row above the plus row, magnitudes aligned", () => {
    const html = buildBlockEditRich(block, "2026-09-10", 0, 0).html!;
    // Two explicit rows per field: a single row of six wraps to 3+3 on its
    // own, so pinning the arrangement means emitting the rows ourselves.
    expect(html.indexOf("−30")).toBeLessThan(html.indexOf("+30"));
    expect(html.indexOf("−30")).toBeLessThan(html.indexOf("−15"));
    expect(html.indexOf("−15")).toBeLessThan(html.indexOf("−5"));
  });

  it("carries the running draft in the callback data", () => {
    const html = buildBlockEditRich(block, "2026-09-10", -15, 30).html!;
    // Each button adds its own step to what is already accumulated.
    expect(html).toContain('data="adj:2026-09-10:e1:-45:30"');  // start −15 then −30
    expect(html).toContain('data="adj:2026-09-10:e1:-10:30"');  // start −15 then +5
    expect(html).toContain('data="adj:2026-09-10:e1:-15:60"');  // end 30 then +30
  });

  it("keeps every callback inside the 64-byte budget", () => {
    const html = buildBlockEditRich(block, "2026-09-10", -120, 120).html!;
    for (const m of html.matchAll(/data="([^"]+)"/g)) {
      expect(new TextEncoder().encode(m[1]!).length).toBeLessThanOrEqual(64);
    }
  });

  it("shows the drafted times, not the stored ones", () => {
    const html = buildBlockEditRich(block, "2026-09-10", 10, -20).html!;
    expect(html).toContain("09:15");
    expect(html).toContain("09:40");
  });

  it("puts the nudge rows inside <td> elements", () => {
    const html = buildBlockEditRich(block, "2026-09-10", 0, 0).html!;
    expect(html).toMatch(/<td><tg-button-row>[\s\S]*?−30[\s\S]*?<\/tg-button-row>/);
  });
});

describe("save and back", () => {
  it("saves with the accumulated deltas", () => {
    const html = buildBlockEditRich(block, "2026-09-10", -15, 30).html!;
    expect(html).toContain('data="adjsave:2026-09-10:e1:-15:30"');
  });

  it("goes back to the day it came from", () => {
    const html = buildBlockEditRich(block, "2026-09-10", 0, 0).html!;
    expect(html).toContain('data="day:2026-09-10"');
  });

  it("offers one save button, not a separate save and approve", () => {
    const html = buildBlockEditRich(block, "2026-09-10", 0, 0).html!;
    expect((html.match(/data="adjsave:/g) ?? []).length).toBe(1);
  });
});

describe("the deferred calendar actions", () => {
  it("renders cancel and delete, delete styled as dangerous", () => {
    const html = buildBlockEditRich(block, "2026-09-10", 0, 0).html!;
    expect(html).toContain("cancel in calendar");
    expect(html).toContain("delete");
    expect(html).toMatch(/data="cal:delete:e1"[^>]*style="danger"|style="danger"[^>]*>delete/);
  });
});

describe("no rename button", () => {
  it("does not offer one", () => {
    // Ship 4 already renames by talking, and a button whose only power is to
    // open a text prompt is not an improvement on saying it.
    const html = buildBlockEditRich(block, "2026-09-10", 0, 0).html!;
    expect(html.toLowerCase()).not.toContain("rename");
  });
});
