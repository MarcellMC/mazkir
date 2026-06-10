import { describe, it, expect } from "vitest";
import {
  taskSlug,
  buildTasksKeyboard,
  buildTaskDetailKeyboard,
} from "../../src/keyboards/tasks.js";
import type { Task } from "@mazkir/shared-types";

const LONG_TASK: Task = {
  name: "Smartomica: Do overview of Arbox and CRM for clinic patients management",
  status: "active",
  priority: 3,
  path: "40-tasks/active/smartomica-do-overview-of-arbox-and-crm-for-clinic.md",
};

const SHORT_TASK: Task = {
  name: "Buy groceries",
  status: "active",
  priority: 2,
  path: "40-tasks/active/buy-groceries.md",
};

describe("taskSlug", () => {
  it("uses the filename stem from path", () => {
    expect(taskSlug(SHORT_TASK)).toBe("buy-groceries");
  });

  it("truncates to 54 bytes so callback_data stays within Telegram's 64-byte limit", () => {
    const slug = taskSlug(LONG_TASK);
    expect(Buffer.byteLength(slug, "utf8")).toBeLessThanOrEqual(54);
    expect("smartomica-do-overview-of-arbox-and-crm-for-clinic".startsWith(slug.slice(0, 50))).toBe(true);
  });

  it("slugifies the name when path is missing", () => {
    const task: Task = { name: "Fix the API!", status: "active", priority: 3 };
    expect(taskSlug(task)).toBe("fix-the-api");
  });
});

describe("buildTasksKeyboard", () => {
  it("every button's callback_data fits Telegram's 64-byte limit", () => {
    const kb = buildTasksKeyboard([LONG_TASK, SHORT_TASK]);
    const buttons = kb.inline_keyboard.flat();
    expect(buttons.length).toBe(2);
    for (const b of buttons) {
      expect("callback_data" in b).toBe(true);
      const data = (b as { callback_data: string }).callback_data;
      expect(Buffer.byteLength(data, "utf8")).toBeLessThanOrEqual(64);
      expect(data.startsWith("task:view:")).toBe(true);
    }
  });

  it("caps the number of buttons", () => {
    const tasks = Array.from({ length: 20 }, (_, i) => ({
      ...SHORT_TASK,
      path: `40-tasks/active/task-${i}.md`,
    }));
    const kb = buildTasksKeyboard(tasks);
    expect(kb.inline_keyboard.flat().length).toBe(8);
  });

  it("labels buttons with sequential numbers", () => {
    const kb = buildTasksKeyboard([LONG_TASK, SHORT_TASK]);
    const buttons = kb.inline_keyboard.flat() as { text: string; callback_data: string }[];
    expect(buttons[0].text).toMatch(/^1\. /);
    expect(buttons[1].text).toMatch(/^2\. /);
  });

  it("sorts by priority before numbering (high first)", () => {
    const high: Task = { name: "Urgent", status: "active", priority: 5, path: "40-tasks/active/urgent.md" };
    const low: Task = { name: "Minor", status: "active", priority: 1, path: "40-tasks/active/minor.md" };
    const kb = buildTasksKeyboard([low, high]);
    const buttons = kb.inline_keyboard.flat() as { text: string; callback_data: string }[];
    expect(buttons[0].text).toMatch(/^1\. Urgent/);
    expect(buttons[1].text).toMatch(/^2\. Minor/);
  });
});

describe("buildTaskDetailKeyboard", () => {
  it("renders Complete and Back buttons with valid callback_data", () => {
    const kb = buildTaskDetailKeyboard("buy-groceries");
    const buttons = kb.inline_keyboard.flat() as { text: string; callback_data: string }[];
    expect(buttons.map((b) => b.callback_data)).toEqual([
      "task:done:buy-groceries",
      "nav:tasks",
    ]);
    for (const b of buttons) {
      expect(Buffer.byteLength(b.callback_data, "utf8")).toBeLessThanOrEqual(64);
    }
  });
});
