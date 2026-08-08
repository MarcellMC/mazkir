import { describe, it, expect } from "vitest";
import { buildConfirmationKeyboard } from "../../src/keyboards/confirmation.js";

describe("buildConfirmationKeyboard", () => {
  it("renders one button per choice, keyed by action id", () => {
    const kb = buildConfirmationKeyboard("act_1", [
      { value: "autonomous", label: "Autonomous" },
      { value: "handoff-checkpoints", label: "Hand-off" },
    ]);

    const buttons = kb.inline_keyboard.flat();
    expect(buttons.map((b) => b.text)).toEqual(["Autonomous", "Hand-off"]);
    expect(buttons.map((b) => (b as { callback_data: string }).callback_data)).toEqual([
      "confirm:act_1:autonomous",
      "confirm:act_1:handoff-checkpoints",
    ]);
  });

  it("puts each choice on its own row so long labels stay readable", () => {
    const kb = buildConfirmationKeyboard("act_1", [
      { value: "a", label: "Hand-off — checkpoints" },
      { value: "b", label: "Hand-off — run through" },
    ]);

    expect(kb.inline_keyboard.length).toBe(2);
  });

  it("returns no buttons for an empty choice list", () => {
    const kb = buildConfirmationKeyboard("act_1", []);

    expect(kb.inline_keyboard.flat()).toEqual([]);
  });
});
