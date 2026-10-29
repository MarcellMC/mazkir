import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("../../src/config.js", () => ({
  config: { botToken: "t", vaultServerUrl: "http://localhost:8000", vaultServerApiKey: "k",
            authorizedUserId: 123, webappUrl: "", logLevel: "INFO", streamResponses: true },
}));
const client = vi.hoisted(() => ({
  api: { sendMessage: vi.fn(), sendConfirmation: vi.fn() },
  streamMessage: vi.fn(),
}));
vi.mock("../../src/api/client.js", () => client);

const { messageHandler } = await import("../../src/conversations/message.js");
const { dropPerMessageHints } = await import("../../src/bot.js");
const { takeOpenQuestion, resetOpenQuestions } = await import("../../src/state/open-question.js");

const line = (over: Record<string, unknown> = {}) => ({
  id: 0, glyph: "✓", when: "18:00–19:00", text: "Gym", detail: null, sync: "⏳ calendar",
  reason: "", status: "done", buttons: [], ...over,
});
const receipt = (over: Record<string, unknown> = {}) => ({
  turn_id: "t0000beef", lines: [line()], undo: "rcpt:t0000beef:u:un", open_question: null,
  text: "✓ Gym", ...over,
});
const synced = receipt({ lines: [line({ sync: "✓ calendar" })] });

/** Every call goes through the real bot-wide transformer, as it does live. */
function through(method: string, result: unknown = { message_id: 50 }) {
  return vi.fn(async (..._args: unknown[]) => {
    await dropPerMessageHints(
      async () => ({ ok: true, result }) as any, method as never, { chat_id: 123 } as never, undefined,
    );
    return result;
  });
}

function makeCtx() {
  const msg = { message_id: 7, date: 1749500000, chat: { id: 123, type: "private" }, text: "gym 6-7" };
  return {
    update: { update_id: 1, message: msg },
    message: msg,
    chat: msg.chat,
    me: { id: 42, is_bot: true, username: "test_bot" },
    replyWithChatAction: through("sendChatAction", true),
    replyWithRichMessageDraft: through("sendRichMessageDraft", true),
    replyWithRichMessage: through("sendRichMessage"),
    reply: through("sendMessage"),
    api: { editMessageText: through("editMessageText", true) },
  } as any;
}

const run = (ctx: any) => messageHandler.middleware()(ctx, async () => {});

describe("streaming a fast-lane turn", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetOpenQuestions();
  });

  it("sends the receipt once, edits it for each update, and adds no reply on a fast turn", async () => {
    client.streamMessage.mockImplementation(async (_p: unknown, h: any) => {
      await h.onStage("Reading…");
      await h.onReceipt(receipt());
      await h.onReceiptUpdate({ line_id: 0, receipt: synced });
      return { response: "✓ Gym", route: "fast", receipt: synced };
    });
    const ctx = makeCtx();
    await run(ctx);

    expect(client.streamMessage.mock.calls[0][0].message_id).toBe(7);
    expect(ctx.replyWithRichMessageDraft).toHaveBeenCalledWith({ markdown: "_Reading…_" }, expect.anything());
    expect(ctx.replyWithRichMessage).toHaveBeenCalledOnce();
    const edits = ctx.api.editMessageText.mock.calls;
    expect(edits.length).toBeGreaterThan(0);
    for (const [chatId, messageId, body] of edits) {
      expect(chatId).toBe(123);
      expect(messageId).toBe(50);
      expect(body.html).toContain("✓ calendar");
    }
    expect(client.api.sendMessage).not.toHaveBeenCalled();
  });

  it("a mixed turn's reply follows its receipt; the receipt is not sent twice", async () => {
    client.streamMessage.mockImplementation(async (_p: unknown, h: any) => {
      await h.onReceipt(receipt());
      await h.onChunk("GQA ");
      await h.onChunk("shares keys");
      return { response: "GQA shares keys", route: "mixed", receipt: receipt() };
    });
    const ctx = makeCtx();
    await run(ctx);
    expect(ctx.replyWithRichMessage).toHaveBeenCalledTimes(2);
    expect(ctx.replyWithRichMessage.mock.calls[1][0]).toEqual({ markdown: "GQA shares keys" });
  });

  it("a receipt_update arriving after the reply's text still edits the receipt", async () => {
    client.streamMessage.mockImplementation(async (_p: unknown, h: any) => {
      await h.onReceipt(receipt());
      await h.onChunk("reply");
      await h.onReceiptUpdate({ line_id: 0, receipt: synced });
      return { response: "reply", route: "mixed", receipt: synced };
    });
    const ctx = makeCtx();
    await run(ctx);
    expect(ctx.api.editMessageText.mock.calls[0][2].html).toContain("✓ calendar");
  });

  it("an update before any receipt message is dropped; the final receipt is sent instead", async () => {
    client.streamMessage.mockImplementation(async (_p: unknown, h: any) => {
      await h.onReceiptUpdate({ line_id: 0, receipt: synced });
      return { response: "✓ Gym", route: "fast", receipt: synced };
    });
    const ctx = makeCtx();
    await run(ctx);
    expect(ctx.api.editMessageText).not.toHaveBeenCalled();
    expect(ctx.replyWithRichMessage).toHaveBeenCalledOnce();
    expect(ctx.replyWithRichMessage.mock.calls[0][0].html).toContain("✓ calendar");
  });

  it("a refused edit costs nothing: the turn still finishes and nothing is resent", async () => {
    client.streamMessage.mockImplementation(async (_p: unknown, h: any) => {
      await h.onReceipt(receipt());
      await h.onReceiptUpdate({ line_id: 0, receipt: synced });
      return { response: "reply", route: "mixed", receipt: synced };
    });
    const ctx = makeCtx();
    ctx.api.editMessageText = vi.fn().mockRejectedValue(
      Object.assign(new Error("Bad Request: message is not modified"), {
        description: "Bad Request: message is not modified",
      }),
    );
    await run(ctx);
    expect(ctx.replyWithRichMessage).toHaveBeenCalledTimes(2);
    expect(client.api.sendMessage).not.toHaveBeenCalled();
    expect(ctx.reply).not.toHaveBeenCalled();
  });

  it("a failed final send never resends the message to the server", async () => {
    client.streamMessage.mockResolvedValue({ response: "reply", route: "mixed", receipt: null });
    const ctx = makeCtx();
    ctx.replyWithRichMessage = vi.fn().mockRejectedValue(new Error("rich refused"));
    ctx.reply = vi.fn().mockRejectedValueOnce(new Error("plain refused")).mockResolvedValue({ message_id: 2 });
    await run(ctx);
    expect(client.api.sendMessage).not.toHaveBeenCalled();
  });

  it("a stream that breaks after its receipt falls back without sending the receipt again", async () => {
    client.streamMessage.mockImplementation(async (_p: unknown, h: any) => {
      await h.onReceipt(receipt());
      throw new Error("connection reset");
    });
    client.api.sendMessage.mockResolvedValue({ response: "✓ Gym", route: "fast", receipt: synced });
    const ctx = makeCtx();
    await run(ctx);
    // Same message id: the server answers the repeat from the first turn.
    expect(client.api.sendMessage.mock.calls[0][0].message_id).toBe(7);
    expect(ctx.replyWithRichMessage).toHaveBeenCalledOnce();
    expect(ctx.api.editMessageText.mock.calls.at(-1)[2].html).toContain("✓ calendar");
  });

  it("arms the receipt's question after the receipt, its edits and the reply", async () => {
    const asked = receipt({ open_question: "A match · no time given. Reply with one." });
    client.streamMessage.mockImplementation(async (_p: unknown, h: any) => {
      await h.onStage("Reading…");
      await h.onReceipt(asked);
      await h.onChunk("noted");
      await h.onReceiptUpdate({ line_id: 0, receipt: asked });
      return { response: "noted", route: "mixed", receipt: asked };
    });
    await run(makeCtx());
    expect(takeOpenQuestion(123)).toBe("A match · no time given. Reply with one.");
  });
});
