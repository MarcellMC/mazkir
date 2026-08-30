import { describe, it, expect } from "vitest";
import { taskSlug } from "../../src/keyboards/tasks.js";
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
