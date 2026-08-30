import { describe, it, expect } from "vitest";
import { buildGoalsRich, buildGoalDetailRich } from "../../src/formatters/goals-rich.js";

const goal = (o: object) => ({
  name: "Ship Mazkir", slug: "ship-mazkir", priority: "high",
  status: "active", progress: 40, target_date: null, ...o,
});
const html = (fn: () => { html?: string }) => fn().html ?? "";

describe("buildGoalsRich", () => {
  it("renders one in-body button per goal", () => {
    const out = html(() => buildGoalsRich([goal({ slug: "ship-mazkir" })] as never));
    expect(out).toContain('data="goal:view:ship-mazkir"');
  });

  it("keeps the progress bar from the old formatter", () => {
    const out = html(() => buildGoalsRich([goal({ progress: 40 })] as never));
    expect(out).toMatch(/40\s*%/);
  });

  it("escapes goal names", () => {
    const out = html(() => buildGoalsRich([goal({ name: "A & B <c>" })] as never));
    expect(out).toContain("A &amp; B &lt;c&gt;");
  });

  it("says so when there are none", () => {
    expect(html(() => buildGoalsRich([] as never))).toContain("No");
  });

  it("keeps every button's callback_data inside Telegram's 64-byte limit", () => {
    // Ported from the deleted buildGoalsKeyboard suite: the limit applies to
    // in-body buttons exactly as it did to keyboard ones.
    const out = html(() => buildGoalsRich([goal({
      name: "Smartomica: overview of Arbox and CRM for clinic patient management",
      path: "30-goals/2026/smartomica-overview-of-arbox-and-crm-for-clinic.md",
    })] as never));
    for (const m of out.matchAll(/data="(goal:view:[^"]*)"/g)) {
      expect(Buffer.byteLength(m[1]!, "utf8")).toBeLessThanOrEqual(64);
    }
  });

  it("caps the buttons and says how many were left out", () => {
    const many = Array.from({ length: 20 }, (_, i) =>
      goal({ name: `G${i}`, path: `30-goals/2026/g-${i}.md` }));
    const out = html(() => buildGoalsRich(many as never));
    expect((out.match(/data="goal:view:/g) ?? []).length).toBeLessThanOrEqual(8);
    expect(out).toContain("more");
  });

  it("numbers buttons to match the body list", () => {
    const out = html(() => buildGoalsRich([
      goal({ name: "First", path: "30-goals/2026/first.md" }),
      goal({ name: "Second", path: "30-goals/2026/second.md" }),
    ] as never));
    const order = [...out.matchAll(/data="goal:view:([^"]*)">(\d+)</g)].map((m) => [m[2], m[1]]);
    expect(order).toEqual([["1", "first"], ["2", "second"]]);
  });
});

describe("buildGoalDetailRich", () => {
  it("offers only Back — goals have no completion endpoint", () => {
    const out = html(() => buildGoalDetailRich(goal({}) as never));
    expect(out).toContain('data="nav:goals"');
    expect(out).not.toContain("goal:done");
  });
});
