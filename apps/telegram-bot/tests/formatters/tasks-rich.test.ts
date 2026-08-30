import { describe, it, expect } from "vitest";
import { buildTasksRich, buildTaskDetailRich } from "../../src/formatters/tasks-rich.js";

const task = (o: object) => ({
  name: "Order dog food", slug: "order-dog-food", priority: 3,
  status: "active", category: null, due_date: null, ...o,
});
const html = (fn: () => { html?: string }) => fn().html ?? "";

describe("buildTasksRich", () => {
  it("renders one in-body button per task", () => {
    const out = html(() => buildTasksRich([
      task({ name: "Order dog food", slug: "order-dog-food" }),
      task({ name: "Fix the bike", slug: "fix-the-bike" }),
    ] as never));
    expect(out).toContain('data="task:view:order-dog-food"');
    expect(out).toContain('data="task:view:fix-the-bike"');
    expect(out).toContain("<tg-button-row");
  });

  it("escapes task names", () => {
    const out = html(() => buildTasksRich([task({ name: "Email <boss> re R&D" })] as never));
    expect(out).toContain("Email &lt;boss&gt; re R&amp;D");
    expect(out).not.toContain("<boss>");
  });

  it("groups by priority, highest first", () => {
    const out = html(() => buildTasksRich([
      task({ name: "Low", priority: 1 }),
      task({ name: "High", priority: 5 }),
    ] as never));
    expect(out.indexOf("High")).toBeLessThan(out.indexOf("Low"));
  });

  it("says so when there is nothing to do", () => {
    expect(html(() => buildTasksRich([] as never))).toContain("No active tasks");
  });

  it("keeps every button's callback_data inside Telegram's 64-byte limit", () => {
    // Ported from the deleted buildTasksKeyboard suite: the limit applies to
    // in-body buttons exactly as it did to keyboard ones, and a long vault
    // filename is what pushes a task over it.
    const out = html(() => buildTasksRich([task({
      name: "Smartomica: Do overview of Arbox and CRM for clinic patients management",
      path: "40-tasks/active/smartomica-do-overview-of-arbox-and-crm-for-clinic.md",
    })] as never));
    for (const m of out.matchAll(/data="(task:view:[^"]*)"/g)) {
      expect(Buffer.byteLength(m[1]!, "utf8")).toBeLessThanOrEqual(64);
    }
  });

  it("numbers buttons to match the body list, priority order", () => {
    // Button `1` must address the task the body printed as `1.`; the two are
    // derived from one sorted array precisely so they cannot drift.
    const out = html(() => buildTasksRich([
      task({ name: "Minor", path: "40-tasks/active/minor.md", priority: 1 }),
      task({ name: "Urgent", path: "40-tasks/active/urgent.md", priority: 5 }),
    ] as never));
    expect(out).toContain("<li>1. ⏳ Urgent</li>");
    expect(out).toContain("<li>2. ⏳ Minor</li>");
    const order = [...out.matchAll(/data="task:view:([^"]*)">(\d+)</g)].map((m) => [m[2], m[1]]);
    expect(order).toEqual([["1", "urgent"], ["2", "minor"]]);
  });

  it("caps the button rows so the message stays usable", () => {
    const many = Array.from({ length: 20 }, (_, i) =>
      task({ name: `T${i}`, slug: `t-${i}` }));
    const out = html(() => buildTasksRich(many as never));
    const buttons = out.match(/data="task:view:/g) ?? [];
    expect(buttons.length).toBeLessThanOrEqual(8);
    expect(out).toContain("more");
  });
});

describe("buildTaskDetailRich", () => {
  it("puts Complete and Back in the body, not the keyboard", () => {
    const out = html(() => buildTaskDetailRich(
      task({ name: "Order dog food", slug: "order-dog-food" }) as never));
    expect(out).toContain('data="task:done:order-dog-food"');
    expect(out).toContain('data="nav:tasks"');
  });

  it("styles Complete as the affirmative action", () => {
    const out = html(() => buildTaskDetailRich(task({}) as never));
    expect(out).toMatch(/data="task:done:[^"]*" style="success"/);
  });
});
