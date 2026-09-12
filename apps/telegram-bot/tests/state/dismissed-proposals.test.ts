import { describe, it, expect, beforeEach } from "vitest";
import {
  SUPPRESS_MS,
  suppressProposal,
  isProposalSuppressed,
  stripSuppressedProposals,
  resetDismissedProposals,
} from "../../src/state/dismissed-proposals.js";

beforeEach(() => resetDismissedProposals());

// The clock is injected rather than faked, so these assert the expiry rule
// itself rather than the behaviour of a timer mock.
const T0 = 1_000_000;

describe("suppressing a proposal", () => {
  it("holds, then lapses", () => {
    suppressProposal(1, "2026-09-12", "00:00", "05:00", T0);

    expect(isProposalSuppressed(1, "2026-09-12", "00:00", "05:00", T0 + 1)).toBe(true);
    expect(
      isProposalSuppressed(1, "2026-09-12", "00:00", "05:00", T0 + SUPPRESS_MS - 1),
    ).toBe(true);
    // "Gone now, may return later" — later has to actually arrive.
    expect(
      isProposalSuppressed(1, "2026-09-12", "00:00", "05:00", T0 + SUPPRESS_MS + 1),
    ).toBe(false);
  });

  it("is keyed by interval, not by day", () => {
    // Two holes in one day may carry the same proposed name; refusing one
    // says nothing about the other.
    suppressProposal(1, "2026-09-12", "00:00", "05:00", T0);

    expect(isProposalSuppressed(1, "2026-09-12", "15:00", "17:00", T0)).toBe(false);
  });

  it("is keyed by date", () => {
    suppressProposal(1, "2026-09-12", "00:00", "05:00", T0);

    expect(isProposalSuppressed(1, "2026-09-11", "00:00", "05:00", T0)).toBe(false);
  });

  it("is keyed by chat", () => {
    suppressProposal(1, "2026-09-12", "00:00", "05:00", T0);

    expect(isProposalSuppressed(2, "2026-09-12", "00:00", "05:00", T0)).toBe(false);
  });

  it("does not grow without bound", () => {
    // Every read and write sweeps, because nothing else reaps this map.
    suppressProposal(1, "2026-09-12", "00:00", "05:00", T0);
    suppressProposal(1, "2026-09-12", "06:00", "07:00", T0);

    // One read past the TTL clears both, so a later suppression starts clean.
    expect(isProposalSuppressed(9, "x", "00:00", "01:00", T0 + SUPPRESS_MS + 1)).toBe(false);
    expect(isProposalSuppressed(1, "2026-09-12", "00:00", "05:00", T0 + 1)).toBe(false);
  });
});

describe("stripSuppressedProposals", () => {
  const day = {
    date: "2026-09-12",
    gaps: [
      { start: "00:00", end: "05:00", proposal: { name: "Sleep" } },
      { start: "15:00", end: "17:00", proposal: { name: "Gym" } },
    ],
  };

  it("removes only the dismissed one and leaves the gap itself", () => {
    suppressProposal(1, "2026-09-12", "00:00", "05:00");

    const out = stripSuppressedProposals(1, day);

    expect(out.gaps[0]!.proposal).toBeNull();
    // The hole is still a hole: that time really is unaccounted, and
    // dropping the row would misreport the day.
    expect(out.gaps[0]!.start).toBe("00:00");
    expect(out.gaps[1]!.proposal).toEqual({ name: "Gym" });
  });

  it("does not mutate its input", () => {
    suppressProposal(1, "2026-09-12", "00:00", "05:00");

    stripSuppressedProposals(1, day);

    expect(day.gaps[0]!.proposal).toEqual({ name: "Sleep" });
  });
});
