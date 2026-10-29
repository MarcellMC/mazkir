import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("../../src/config.js", () => ({
  config: { botToken: "t", vaultServerUrl: "http://localhost:8000", vaultServerApiKey: "k",
            authorizedUserId: 1, webappUrl: "", logLevel: "INFO", streamResponses: false },
}));
vi.mock("../../src/api/client.js", () => ({ api: { sendMessage: vi.fn(), sendConfirmation: vi.fn() }, streamMessage: vi.fn() }));

const { sendFinal } = await import("../../src/conversations/message.js");
const { takeOpenQuestion, resetOpenQuestions } = await import("../../src/state/open-question.js");

const line = {
  id: 0, glyph: "✓", when: "18:00–19:00", text: "Gym", detail: null, sync: null, reason: "",
  status: "done", buttons: [],
};
const receipt = { turn_id: "t0000beef", lines: [line], undo: null, open_question: null, text: "✓ Gym" };

function ctx() {
  return { replyWithRichMessage: vi.fn().mockResolvedValue({ message_id: 1 }), reply: vi.fn() } as any;
}

describe("sendFinal", () => {
  beforeEach(() => resetOpenQuestions());

  it("a fast turn is its receipt alone", async () => {
    const c = ctx();
    await sendFinal(c, 1, { response: "✓ Gym", route: "fast", receipt } as any, false);
    expect(c.replyWithRichMessage).toHaveBeenCalledOnce();
    expect(c.replyWithRichMessage.mock.calls[0][0].html).toContain("<table>");
  });

  it("a fast turn whose receipt failed to render sends the server's text", async () => {
    const c = ctx();
    await sendFinal(c, 1, {
      response: "(the receipt for this message could not be shown)", route: "fast", receipt: null,
    } as any, false);
    expect(c.replyWithRichMessage).toHaveBeenCalledOnce();
    expect(c.replyWithRichMessage.mock.calls[0][0]).toEqual({
      markdown: "(the receipt for this message could not be shown)",
    });
  });

  it("a mixed turn sends the receipt, then the skill's reply", async () => {
    const c = ctx();
    await sendFinal(c, 1, { response: "GQA shares keys", route: "mixed", receipt } as any, false);
    expect(c.replyWithRichMessage).toHaveBeenCalledTimes(2);
    expect(c.replyWithRichMessage.mock.calls[0][0].html).toContain("<table>");
    expect(c.replyWithRichMessage.mock.calls[1][0]).toEqual({ markdown: "GQA shares keys" });
  });

  it("a receipt already sent while streaming is not sent again", async () => {
    const c = ctx();
    await sendFinal(c, 1, { response: "reply", route: "mixed", receipt } as any, true);
    expect(c.replyWithRichMessage).toHaveBeenCalledOnce();
    expect(c.replyWithRichMessage.mock.calls[0][0]).toEqual({ markdown: "reply" });
  });

  it("a question is held for the next message", async () => {
    await sendFinal(ctx(), 1, { response: "", route: "fast",
      receipt: { ...receipt, open_question: "A match · no time given. Reply with one." } } as any, false);
    expect(takeOpenQuestion(1)).toBe("A match · no time given. Reply with one.");
  });

  it("the old server's reply is sent as before", async () => {
    const c = ctx();
    await sendFinal(c, 1, { response: "hello" } as any, false);
    expect(c.replyWithRichMessage).toHaveBeenCalledOnce();
    expect(c.replyWithRichMessage.mock.calls[0][0]).toEqual({ markdown: "hello" });
  });

  it("a confirmation's choices ride on the reply", async () => {
    const c = ctx();
    await sendFinal(c, 1, {
      response: "Run it?", route: "fallthrough", receipt: null, awaiting_confirmation: true,
      pending_action_id: "a1", confirmation_choices: [{ value: "yes", label: "Yes" }],
    } as any, false);
    expect(c.replyWithRichMessage.mock.calls[0][1]).toHaveProperty("reply_markup");
  });
});
