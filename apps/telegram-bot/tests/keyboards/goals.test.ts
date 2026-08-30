import { describe, it, expect } from "vitest";
import {
  goalSlug,
  buildGoalsKeyboard,
  buildGoalDetailKeyboard,
} from "../../src/keyboards/goals.js";
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

describe("buildGoalsKeyboard", () => {
  it("every goal button's callback_data fits Telegram's 64-byte limit", () => {
    const kb = buildGoalsKeyboard([LONG_GOAL, SHORT_GOAL]);
    const buttons = kb.inline_keyboard.flat().filter(
      (b) => (b as { callback_data?: string }).callback_data?.startsWith("goal:view:"),
    );
    expect(buttons.length).toBe(2);
    for (const b of buttons) {
      const data = (b as { callback_data: string }).callback_data;
      expect(Buffer.byteLength(data, "utf8")).toBeLessThanOrEqual(64);
    }
  });

  it("caps the number of goal buttons, independent of the Day button", () => {
    const goals = Array.from({ length: 20 }, (_, i) => ({
      ...SHORT_GOAL,
      path: `30-goals/2026/goal-${i}.md`,
    }));
    const kb = buildGoalsKeyboard(goals);
    const goalButtons = kb.inline_keyboard.flat().filter(
      (b) => (b as { callback_data?: string }).callback_data?.startsWith("goal:view:"),
    );
    expect(goalButtons.length).toBe(8);
  });

  it("preserves server order and numbers buttons to match the message body", () => {
    const kb = buildGoalsKeyboard([LONG_GOAL, SHORT_GOAL]);
    const buttons = kb.inline_keyboard.flat() as { text: string; callback_data: string }[];
    expect(buttons[0].text).toMatch(/^1\. Ship the personal assistant/);
    expect(buttons[1].text).toMatch(/^2\. Get fit$/);
  });

  it("puts one goal per row, plus the cross-view Day row at the bottom", () => {
    const kb = buildGoalsKeyboard([LONG_GOAL, SHORT_GOAL]);
    expect(kb.inline_keyboard.map((row) => row.length)).toEqual([1, 1, 1]);
    const buttons = kb.inline_keyboard.flat() as { text: string; callback_data: string }[];
    expect(buttons[buttons.length - 1]).toEqual({ text: "📅 Day", callback_data: "nav:day" });
  });

  it("still renders the Day button when there are no goals", () => {
    expect(buildGoalsKeyboard([]).inline_keyboard.flat()).toEqual([
      { text: "📅 Day", callback_data: "nav:day" },
    ]);
  });
});

describe("buildGoalDetailKeyboard", () => {
  it("renders a Back button pointing at the goals list", () => {
    const kb = buildGoalDetailKeyboard();
    const buttons = kb.inline_keyboard.flat() as { text: string; callback_data: string }[];
    expect(buttons.map((b) => b.callback_data)).toEqual(["nav:goals"]);
  });
});
