import { describe, it, expect } from "vitest";
import { goalSlug } from "../../src/keyboards/goals.js";
import type { Goal } from "@mazkir/shared-types";

const LONG_GOAL: Goal = {
  name: "Ship the personal assistant with habits, goals and knowledge recall",
  status: "in-progress",
  priority: "high",
  progress: 30,
  path: "30-goals/2026/ship-the-personal-assistant-with-habits-goals-and-knowledge-recall.md",
};

const SHORT_GOAL: Goal = {
  name: "Get fit",
  status: "in-progress",
  priority: "medium",
  progress: 40,
  path: "30-goals/2026/get-fit.md",
};

describe("goalSlug", () => {
  it("uses the filename stem from path", () => {
    expect(goalSlug(SHORT_GOAL)).toBe("get-fit");
  });

  it("truncates to 54 bytes so callback_data stays within Telegram's 64-byte limit", () => {
    const slug = goalSlug(LONG_GOAL);
    expect(Buffer.byteLength(slug, "utf8")).toBe(54);
    expect(
      "30-goals/2026/ship-the-personal-assistant-with-habits-goals-and-knowledge-recall.md".includes(slug),
    ).toBe(true);
  });

  it("slugifies the name when path is missing", () => {
    const goal: Goal = { name: "Run a marathon!", status: "not-started", priority: "low", progress: 0 };
    expect(goalSlug(goal)).toBe("run-a-marathon");
  });
});
