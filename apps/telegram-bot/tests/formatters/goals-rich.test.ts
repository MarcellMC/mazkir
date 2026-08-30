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

// Ported from the deleted formatGoals / formatGoalDetail suites in
// telegram.test.ts. These assert what the messages SAY, which the move to a
// rich message was not supposed to change — only where the buttons live.
describe("buildGoalsRich priority mapping", () => {
  it("maps the vault's string priorities onto the emoji scale", () => {
    const high = html(() => buildGoalsRich([
      goal({ name: "A", priority: "high", progress: 0 })] as never));
    const low = html(() => buildGoalsRich([
      goal({ name: "B", priority: "low", progress: 0 })] as never));
    expect(high).toContain("🔴");
    expect(low).toContain("🟢");
  });

  it("still maps the older numeric scale", () => {
    expect(html(() => buildGoalsRich([goal({ priority: 5 })] as never))).toContain("🔴");
    expect(html(() => buildGoalsRich([goal({ priority: 3 })] as never))).toContain("🟡");
  });
});

describe("buildGoalDetailRich body", () => {
  const GOAL = {
    name: "Get fit <2026>",
    slug: "get-fit",
    status: "in-progress",
    priority: "high",
    progress: 40,
    category: "health",
    start_date: "2026-01-01",
    target_date: "2026-12-31",
    path: "30-goals/2026/get-fit.md",
    milestones: ["Run 5k", "Run 10k"],
    content: "# Get fit\n\n## Why\nFeel better & live longer\n\n## Checklist\n- [ ]\n",
  };

  it("renders progress, priority, status and dates", () => {
    const out = html(() => buildGoalDetailRich(GOAL as never));
    expect(out).toMatch(/40\s*%/);
    expect(out).toContain("Priority: <b>high</b>");
    expect(out).toContain("Status: in-progress");
    expect(out).toContain("Started: 2026-01-01");
    expect(out).toContain("Target: 2026-12-31");
  });

  it("includes the note body but drops the title and empty sections", () => {
    const out = html(() => buildGoalDetailRich(GOAL as never));
    expect(out).toContain("## Why");
    expect(out).not.toContain("## Checklist");
    expect(out).not.toContain("# Get fit\n");
  });

  it("lists string milestones and ignores richer entries", () => {
    const out = html(() => buildGoalDetailRich({
      ...GOAL, milestones: ["Run 5k", { name: "structured" }],
    } as never));
    expect(out).toContain("Run 5k");
    expect(out).not.toContain("structured");
  });

  it("omits the milestones block when there are none", () => {
    expect(html(() => buildGoalDetailRich({ ...GOAL, milestones: [] } as never)))
      .not.toContain("Milestones");
  });

  it("escapes HTML in the name and body", () => {
    const out = html(() => buildGoalDetailRich(GOAL as never));
    expect(out).toContain("Get fit &lt;2026&gt;");
    expect(out).toContain("Feel better &amp; live longer");
    expect(out).not.toContain("<2026>");
  });

  it("renders without a content field at all", () => {
    // `content` is optional on the wire; an unguarded stripEmptySections
    // would throw on undefined and take the whole message with it.
    const { content, ...noContent } = GOAL;
    expect(() => buildGoalDetailRich(noContent as never)).not.toThrow();
  });
});
