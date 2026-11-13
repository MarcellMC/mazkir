import { describe, it, expect, beforeEach } from "vitest";
import {
  DRAFT_TTL_MS, clearNudgeDraft, draftContext, noteNudgeDraft, resetNudgeDrafts, takeNudgeDraft,
} from "../../src/state/nudge-draft.js";

const D = { date: "2026-11-13", eventId: "evt_1", name: "Dog walk", start: "07:25", end: "08:10" };

describe("nudge draft", () => {
  beforeEach(() => resetNudgeDrafts());

  it("is one-shot", () => {
    noteNudgeDraft(1, D, 0);
    expect(takeNudgeDraft(1, 1)).toEqual(D);
    expect(takeNudgeDraft(1, 2)).toBeUndefined();
  });

  it("expires after 10 minutes", () => {
    noteNudgeDraft(1, D, 0);
    expect(DRAFT_TTL_MS).toBe(10 * 60 * 1000);
    expect(takeNudgeDraft(1, DRAFT_TTL_MS + 1)).toBeUndefined();
  });

  it("clearNudgeDraft with another event id leaves it", () => {
    noteNudgeDraft(1, D, 0);
    clearNudgeDraft(1, "evt_2");
    expect(takeNudgeDraft(1, 1)).toEqual(D);
    noteNudgeDraft(1, D, 0);
    clearNudgeDraft(1, "evt_1");
    expect(takeNudgeDraft(1, 1)).toBeUndefined();
  });

  it("describes itself for the agent", () => {
    expect(draftContext(D)).toBe(
      'Unsaved time edit on block "Dog walk" (id evt_1, 2026-11-13): 07:25–08:10. '
      + "Apply these times together with whatever this message changes, in one update_event.");
  });
});
