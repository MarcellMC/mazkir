import { describe, it, expect, beforeEach } from "vitest";
import {
  QUESTION_TTL_MS,
  noteOpenQuestion,
  takeOpenQuestion,
  clearOpenQuestion,
  resetOpenQuestions,
} from "../../src/state/open-question.js";

beforeEach(() => resetOpenQuestions());

const T0 = 1_000_000;
const Q = "15:00–17:30 on 2026-09-12 is unaccounted — what was it?";

describe("the bot's own open question", () => {
  it("is handed back once and then forgotten", () => {
    noteOpenQuestion(1, Q, T0);

    expect(takeOpenQuestion(1, T0 + 1)).toBe(Q);
    // One answer per question: leaving it attachable would let a stale
    // interval ride along on a later, unrelated message.
    expect(takeOpenQuestion(1, T0 + 2)).toBeUndefined();
  });

  it("lapses rather than attaching to a much later message", () => {
    noteOpenQuestion(1, Q, T0);

    expect(takeOpenQuestion(1, T0 + QUESTION_TTL_MS + 1)).toBeUndefined();
  });

  it("is per chat", () => {
    noteOpenQuestion(1, Q, T0);

    expect(takeOpenQuestion(2, T0 + 1)).toBeUndefined();
    expect(takeOpenQuestion(1, T0 + 1)).toBe(Q);
  });

  it("can be dropped when the user moves on", () => {
    noteOpenQuestion(1, Q, T0);
    clearOpenQuestion(1);

    expect(takeOpenQuestion(1, T0 + 1)).toBeUndefined();
  });
});
