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
