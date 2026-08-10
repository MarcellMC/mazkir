import { describe, it, expect } from "vitest";
import {
  goalSlug,
  buildGoalsKeyboard,
  buildGoalDetailKeyboard,
} from "../../src/keyboards/goals.js";
import type { Goal } from "@mazkir/shared-types";

const LONG_GOAL: Goal = {
  name: "Launch Mazkir personal assistant to production with full observability",
  status: "in-progress",
  priority: 4,
  progress: 40,
  path: "30-goals/2026/launch-mazkir-personal-assistant-to-production-with-full-observability.md",
};

const SHORT_GOAL: Goal = {
  name: "Learn Spanish",
  status: "in-progress",
  priority: 2,
  progress: 10,
  path: "30-goals/2026/learn-spanish.md",
};

describe("goalSlug", () => {
  it("uses the filename stem from path", () => {
    expect(goalSlug(SHORT_GOAL)).toBe("learn-spanish");
  });

  it("truncates to 54 bytes so callback_data stays within Telegram's 64-byte limit", () => {
    const slug = goalSlug(LONG_GOAL);
    expect(Buffer.byteLength(slug, "utf8")).toBeLessThanOrEqual(54);
    expect(
      "launch-mazkir-personal-assistant-to-production-with-full-observability".startsWith(slug),
    ).toBe(true);
  });

  it("slugifies the name when path is missing", () => {
    const goal: Goal = { name: "Ship the API!", status: "in-progress", priority: 3, progress: 0 };
    expect(goalSlug(goal)).toBe("ship-the-api");
  });
});

describe("buildGoalsKeyboard", () => {
  it("every button's callback_data fits Telegram's 64-byte limit", () => {
    const kb = buildGoalsKeyboard([LONG_GOAL, SHORT_GOAL]);
    const buttons = kb.inline_keyboard.flat();
    expect(buttons.length).toBe(2);
    for (const b of buttons) {
      expect("callback_data" in b).toBe(true);
      const data = (b as { callback_data: string }).callback_data;
      expect(Buffer.byteLength(data, "utf8")).toBeLessThanOrEqual(64);
      expect(data.startsWith("goal:view:")).toBe(true);
    }
  });

  it("caps the number of buttons", () => {
    const goals = Array.from({ length: 20 }, (_, i) => ({
      ...SHORT_GOAL,
      path: `30-goals/2026/goal-${i}.md`,
    }));
    const kb = buildGoalsKeyboard(goals);
    expect(kb.inline_keyboard.flat().length).toBe(8);
  });

  it("labels buttons with sequential numbers", () => {
    const kb = buildGoalsKeyboard([LONG_GOAL, SHORT_GOAL]);
    const buttons = kb.inline_keyboard.flat() as { text: string; callback_data: string }[];
    expect(buttons[0].text).toMatch(/^1\. /);
    expect(buttons[1].text).toMatch(/^2\. /);
  });
});

describe("buildGoalDetailKeyboard", () => {
  it("renders a Back button targeting the goals list", () => {
    const kb = buildGoalDetailKeyboard();
    const buttons = kb.inline_keyboard.flat() as { text: string; callback_data: string }[];
    expect(buttons.map((b) => b.callback_data)).toEqual(["nav:goals"]);
  });
});
