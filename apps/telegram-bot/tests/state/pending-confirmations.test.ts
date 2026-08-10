import { describe, it, expect, beforeEach } from "vitest";
import {
  getPendingConfirmation,
  setPendingConfirmation,
  clearPendingConfirmation,
} from "../../src/state/pending-confirmations.js";

describe("pending confirmations", () => {
  beforeEach(() => clearPendingConfirmation(1));

  it("round-trips an action id per chat", () => {
    setPendingConfirmation(1, "act_1");

    expect(getPendingConfirmation(1)).toBe("act_1");
    expect(getPendingConfirmation(2)).toBeUndefined();
  });

  it("clears an answered confirmation", () => {
    setPendingConfirmation(1, "act_1");

    clearPendingConfirmation(1);

    expect(getPendingConfirmation(1)).toBeUndefined();
  });

  it("is shared state, so answering by button stops the text path claiming the next message", () => {
    // A button answer clears the entry; the text handler must then treat
    // the user's next message as a new request, not as a confirmation
    // reply to an action the server has already consumed.
    setPendingConfirmation(1, "act_1");

    clearPendingConfirmation(1);

    expect(getPendingConfirmation(1)).toBeUndefined();
  });
});
