import { describe, it, expect } from "vitest";
import { buildNavKeyboard } from "../../src/keyboards/nav.js";

function labels(kb: ReturnType<typeof buildNavKeyboard>): string[] {
  return kb.inline_keyboard.flat().map((b) => b.text);
}
function data(kb: ReturnType<typeof buildNavKeyboard>): string[] {
  return kb.inline_keyboard.flat().map((b) => ("callback_data" in b ? b.callback_data : ""));
}

describe("buildNavKeyboard", () => {
  it("offers the other three views, never the current one", () => {
    expect(data(buildNavKeyboard("day"))).toEqual(["nav:tasks", "nav:habits", "nav:goals"]);
    expect(data(buildNavKeyboard("tasks"))).toEqual(["nav:day", "nav:habits", "nav:goals"]);
    expect(data(buildNavKeyboard("goals"))).toEqual(["nav:day", "nav:tasks", "nav:habits"]);
  });

  it("keeps a stable order so buttons do not move between views", () => {
    // Day first where present, then tasks, habits, goals — so a given view
    // always sits in the same position and taps become muscle memory.
    expect(labels(buildNavKeyboard("habits"))).toEqual(["📅 Day", "📋 Tasks", "🎯 Goals"]);
  });

  it("fits on one row", () => {
    expect(buildNavKeyboard("day").inline_keyboard).toHaveLength(1);
  });
});
