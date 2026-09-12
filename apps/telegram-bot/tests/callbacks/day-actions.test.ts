import { describe, it, expect, vi, beforeEach } from "vitest";

const api = vi.hoisted(() => ({
  getDaily: vi.fn(), setBlockState: vi.fn(), approveAll: vi.fn(),
  fillGap: vi.fn(), patchEvent: vi.fn(),
}));
vi.mock("../../src/api/client.js", () => ({ api }));

const richMocks = vi.hoisted(() => ({ editRich: vi.fn(), sendRich: vi.fn() }));
vi.mock("../../src/bot-utils/send-rich.js", () => richMocks);

import { dayActionHandlers } from "../../src/callbacks/day-actions.js";

/** Drive one callback through the Composer's middleware. */
async function fire(data: string) {
  const ctx: any = {
    callbackQuery: { data },
    chat: { id: 1 },
    update: { callback_query: { data } },
    answerCallbackQuery: vi.fn(),
    editMessageText: vi.fn(),
    reply: vi.fn(),
  };
  await dayActionHandlers.middleware()(ctx, async () => {});
  return ctx;
}

const emptyDay = {
  date: "2026-09-10", tokens_today: 0, tokens_total: 0,
  blocks: [], gaps: [], incomplete: [], todos: [], notes: [],
  coverage: {
    covered_minutes: 0, unaccounted_minutes: 0, elapsed_minutes: 720,
    confirmed_minutes: 0, pending_minutes: 0,
  },
};

beforeEach(() => {
  vi.clearAllMocks();
  api.getDaily.mockResolvedValue(emptyDay);
});

describe("block controls", () => {
  it("approve calls the state endpoint and re-renders", async () => {
    api.setBlockState.mockResolvedValue({ ok: true, state: "approved", habit: null });

    await fire("block:approve:2026-09-10:e1");

    expect(api.setBlockState).toHaveBeenCalledWith("2026-09-10", "e1", "approved");
    expect(richMocks.editRich).toHaveBeenCalled();
  });

  it("dismiss calls the state endpoint with dismissed", async () => {
    api.setBlockState.mockResolvedValue({ ok: true, state: "dismissed", habit: null });

    await fire("block:dismiss:2026-09-10:e1");

    expect(api.setBlockState).toHaveBeenCalledWith("2026-09-10", "e1", "dismissed");
  });

  it("says what a habit approval paid", async () => {
    api.setBlockState.mockResolvedValue({
      ok: true, state: "approved",
      habit: { name: "Dog walk", tokens_earned: 5, new_streak: 13 },
    });

    const ctx = await fire("block:approve:2026-09-10:e1");

    const said = ctx.answerCallbackQuery.mock.calls[0][0].text as string;
    expect(said).toContain("5");
    expect(said).toContain("13");
  });

  it("reports a 409 as a toast without wiping the day", async () => {
    api.setBlockState.mockRejectedValue(new Error("409 untick it in /habits"));

    const ctx = await fire("block:dismiss:2026-09-10:e1");

    expect(ctx.answerCallbackQuery).toHaveBeenCalled();
    expect(ctx.editMessageText).not.toHaveBeenCalled();
  });
});

describe("proposals", () => {
  it("approving one fills the gap with no name, letting the server decide", async () => {
    api.fillGap.mockResolvedValue({
      ok: true, event_id: "n1", name: "Sleep", was_guess: true,
    });

    await fire("prop:approve:2026-09-10:20:400");

    expect(api.fillGap).toHaveBeenCalledWith("2026-09-10", "00:20", "06:40", undefined);
  });

  it("dismissing one writes nothing at all", async () => {
    await fire("prop:dismiss:2026-09-10:20:400");

    // §4.3, deliberate: a refused proposal reappears rather than leaving a
    // dead row behind. If this ever starts writing, that decision was
    // reversed without anyone saying so.
    expect(api.fillGap).not.toHaveBeenCalled();
    expect(api.setBlockState).not.toHaveBeenCalled();
    expect(api.patchEvent).not.toHaveBeenCalled();
  });
});

describe("gap fill", () => {
  it("asks what the span was rather than guessing", async () => {
    const ctx = await fire("gap:fill:2026-09-10:780:855");

    expect(api.fillGap).not.toHaveBeenCalled();
    expect(ctx.reply).toHaveBeenCalled();
    expect(ctx.reply.mock.calls[0][0]).toContain("13:00");
    expect(ctx.reply.mock.calls[0][0]).toContain("14:15");
  });
});

describe("approve all", () => {
  it("names the guesses it banked", async () => {
    api.approveAll.mockResolvedValue({
      ok: true,
      approved: [
        { event_id: "e1", name: "Standup", was_guess: false },
        { event_id: "n1", name: "Sleep", was_guess: true },
      ],
      failed: [],
    });

    const ctx = await fire("day:approveall:2026-09-10");

    const said = ctx.answerCallbackQuery.mock.calls[0][0].text as string;
    expect(said).toContain("2");
    expect(said.toLowerCase()).toContain("guess");
    expect(said).toContain("Sleep");
  });

  it("reports failures alongside successes", async () => {
    api.approveAll.mockResolvedValue({
      ok: true,
      approved: [{ event_id: "e1", name: "Standup", was_guess: false }],
      failed: [{ event_id: "e2", reason: "untick it in /habits" }],
    });

    const ctx = await fire("day:approveall:2026-09-10");

    expect(ctx.answerCallbackQuery.mock.calls[0][0].text).toContain("1 could not");
  });
});

describe("refresh", () => {
  it("re-renders the day for the date in the callback", async () => {
    await fire("day:refresh:2026-09-10");

    expect(api.getDaily).toHaveBeenCalledWith("2026-09-10");
    expect(richMocks.editRich).toHaveBeenCalled();
  });

  it("reports a failed refresh as a failure, not as success", async () => {
    api.getDaily.mockRejectedValue(new Error("boom"));

    const ctx = await fire("day:refresh:2026-09-10");

    expect(ctx.answerCallbackQuery).toHaveBeenCalledTimes(1);
    expect(ctx.answerCallbackQuery.mock.calls[0][0].text).not.toContain("Refreshed");
  });
});

describe("the edit view", () => {
  it("a nudge re-renders without writing anything", async () => {
    api.getDaily.mockResolvedValue({
      ...emptyDay,
      blocks: [{
        id: "e1", start: "09:05", end: "10:00", title: "Standup",
        source: "calendar", type: "event", completed: false,
        activity: null, category: null, state: "pending", habit_progress: null,
      }],
    });

    await fire("adj:2026-09-10:e1:-15:0");

    expect(api.patchEvent).not.toHaveBeenCalled();
    expect(api.setBlockState).not.toHaveBeenCalled();
    expect(richMocks.editRich).toHaveBeenCalled();
  });

  it("tells you when the block is gone, answering exactly once", async () => {
    api.getDaily.mockResolvedValue(emptyDay);   // no blocks

    const ctx = await fire("adj:2026-09-10:missing:-15:0");

    expect(ctx.answerCallbackQuery).toHaveBeenCalledTimes(1);
    expect(ctx.answerCallbackQuery.mock.calls[0][0].text).toContain("gone");
    expect(richMocks.editRich).not.toHaveBeenCalled();
  });

  it("save patches the times and approves in one go", async () => {
    api.getDaily.mockResolvedValue({
      ...emptyDay,
      blocks: [{
        id: "e1", start: "09:05", end: "10:00", title: "Standup",
        source: "calendar", type: "event", completed: false,
        activity: null, category: null, state: "pending", habit_progress: null,
      }],
    });
    api.patchEvent.mockResolvedValue({});
    api.setBlockState.mockResolvedValue({ ok: true, state: "approved", habit: null });

    await fire("adjsave:2026-09-10:e1:-15:0");

    expect(api.patchEvent).toHaveBeenCalledWith("2026-09-10", "e1", {
      start_time: "2026-09-10T08:50",
      end_time: "2026-09-10T10:00",
    });
    expect(api.setBlockState).toHaveBeenCalledWith("2026-09-10", "e1", "approved");
  });

  it("save with no change still approves", async () => {
    api.getDaily.mockResolvedValue({
      ...emptyDay,
      blocks: [{
        id: "e1", start: "09:05", end: "10:00", title: "Standup",
        source: "calendar", type: "event", completed: false,
        activity: null, category: null, state: "pending", habit_progress: null,
      }],
    });
    api.setBlockState.mockResolvedValue({ ok: true, state: "approved", habit: null });

    await fire("adjsave:2026-09-10:e1:0:0");

    expect(api.patchEvent).not.toHaveBeenCalled();
    expect(api.setBlockState).toHaveBeenCalled();
  });

  it("cancel and delete say they are not wired up", async () => {
    const ctx = await fire("cal:delete:e1");

    expect(api.patchEvent).not.toHaveBeenCalled();
    expect(ctx.answerCallbackQuery.mock.calls[0][0].text).toContain("Not wired up");
  });
});

describe("dismissing a proposal makes it go away", () => {
  // The reported bug: ✕ answered "Skipped" and then the re-render recomputed
  // and redrew the very same row, so nothing appeared to happen. The write
  // still never reaches the vault (asserted above); what changed is that the
  // re-render no longer contradicts the toast.
  // Two proposals, so the test can tell "the dismissed one went" from
  // "proposals stopped rendering".
  const dayWithSleepProposal = {
    ...emptyDay,
    gaps: [
      { start: "00:00", end: "05:00", minutes: 300,
        proposal: { name: "Sleep", days_seen: 0 } },
      { start: "15:00", end: "17:00", minutes: 120,
        proposal: { name: "Gym", days_seen: 5 } },
    ],
  };

  beforeEach(async () => {
    const { resetDismissedProposals } = await import(
      "../../src/state/dismissed-proposals.js"
    );
    resetDismissedProposals();
    api.getDaily.mockResolvedValue(dayWithSleepProposal);
  });

  /** The HTML the day view was actually rendered with on the last edit. */
  function renderedHtml(): string {
    const calls = richMocks.editRich.mock.calls;
    return (calls[calls.length - 1]![1] as { html: string }).html;
  }

  it("strips the dismissed proposal from the re-render", async () => {
    await fire("prop:dismiss:2026-09-10:0:300");

    // Asserted on the rendered markup, not on the store: the bug was that
    // the row came back on screen, so the screen is what has to be checked.
    // Before the fix this still contained "Sleep?".
    expect(renderedHtml()).not.toContain("Sleep?");
    // The untouched gap still offers its own guess — otherwise this would
    // also pass if proposals had simply stopped rendering altogether.
    expect(renderedHtml()).toContain("Gym?");
  });

  it("leaves a different chat's view alone", async () => {
    const { stripSuppressedProposals } = await import(
      "../../src/state/dismissed-proposals.js"
    );

    await fire("prop:dismiss:2026-09-10:0:300");

    expect(stripSuppressedProposals(999, dayWithSleepProposal).gaps[0]!.proposal)
      .toEqual({ name: "Sleep", days_seen: 0 });
    // ...and this chat's own view really did lose it, so the assertion above
    // is about the chat key and not about suppression having failed.
    expect(stripSuppressedProposals(1, dayWithSleepProposal).gaps[0]!.proposal)
      .toBeNull();
  });

  it("still writes nothing to the server", async () => {
    await fire("prop:dismiss:2026-09-10:0:300");

    expect(api.fillGap).not.toHaveBeenCalled();
    expect(api.setBlockState).not.toHaveBeenCalled();
    expect(api.patchEvent).not.toHaveBeenCalled();
  });
});

describe("editing a proposal opens the nudge pad", () => {
  // The other half of the report: ✎ on a suggestion replied with a text
  // prompt, so the 5/15/30 nudge view was unreachable from a gap. It now
  // banks the guess and edits the block that creates.
  it("fills the gap then renders the edit view, not a chat prompt", async () => {
    api.fillGap.mockResolvedValue({
      ok: true, event_id: "n1", name: "Sleep", was_guess: true,
    });
    api.getDaily.mockResolvedValue({
      ...emptyDay,
      blocks: [{
        id: "n1", start: "00:00", end: "05:00", title: "Sleep",
        source: "manual", type: "manual", completed: false,
        activity: null, category: null, state: "approved",
        habit_progress: null,
      }],
    });

    const ctx = await fire("prop:edit:2026-09-10:0:300");

    // Server decides the name (§4.2): no name is sent.
    expect(api.fillGap).toHaveBeenCalledWith("2026-09-10", "00:00", "05:00", undefined);
    expect(richMocks.editRich).toHaveBeenCalled();
    expect(ctx.reply).not.toHaveBeenCalled();
  });

  it("falls back to asking when the server has nothing to propose", async () => {
    api.fillGap.mockRejectedValue(new Error("API error: 422 nothing to propose"));

    const ctx = await fire("prop:edit:2026-09-10:780:855");

    expect(ctx.reply).toHaveBeenCalled();
    const asked = ctx.reply.mock.calls[0][0] as string;
    expect(asked).toContain("13:00");
    expect(asked).toContain("14:15");
  });
});

describe("the gap-fill prompt is answerable in one reply", () => {
  it("states the interval as known and asks only for the activity", async () => {
    const ctx = await fire("gap:fill:2026-09-10:780:855");

    const asked = ctx.reply.mock.calls[0][0] as string;
    // The old wording ("what was that? Just tell me") invited a bare time
    // range, which then needed a second turn to get the activity — the
    // three-turn round trip seen on 2026-09-12.
    expect(asked).toContain("13:00");
    expect(asked).toMatch(/activity/i);
  });
});

describe("the gap prompt leaves the question findable", () => {
  beforeEach(async () => {
    const { resetOpenQuestions } = await import("../../src/state/open-question.js");
    resetOpenQuestions();
  });

  it("arms the question it just asked", async () => {
    const { takeOpenQuestion } = await import("../../src/state/open-question.js");

    const ctx = await fire("gap:fill:2026-09-10:900:1050");

    // Whatever the user was shown is exactly what is remembered, so the
    // agent reads the same interval the user did.
    const asked = ctx.reply.mock.calls[0][0] as string;
    expect(takeOpenQuestion(1)).toBe(asked);
    expect(asked).toContain("15:00");
    expect(asked).toContain("17:30");
  });

  it("arms it after the send, not before", async () => {
    // The bot-wide transformer clears these hints on every send, so arming
    // before ctx.reply would be undone by that very reply. Nothing here can
    // see the transformer, so this asserts the observable consequence: the
    // question survives the send that announced it.
    const { takeOpenQuestion } = await import("../../src/state/open-question.js");

    await fire("gap:fill:2026-09-10:900:1050");

    expect(takeOpenQuestion(1)).toBeDefined();
  });
});
