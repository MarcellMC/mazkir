import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("../../src/config.js", () => ({
  config: {
    botToken: "test-token",
    vaultServerUrl: "http://localhost:8000",
    vaultServerApiKey: "test-key",
    authorizedUserId: 123,
    webappUrl: "http://localhost:5173",
    logLevel: "INFO",
  },
}));

vi.mock("../../src/api/client.js", () => ({
  api: {
    sendMessage: vi.fn(),
    sendConfirmation: vi.fn(),
  },
}));

// Test the extraction helpers (exported for testing)
const { buildMessagePayload } = await import(
  "../../src/conversations/message.js"
);

describe("buildMessagePayload", () => {
  it("builds payload from plain text message", () => {
    const msg = {
      text: "hello",
      caption: undefined,
      photo: undefined,
      location: undefined,
      venue: undefined,
      reply_to_message: undefined,
      forward_origin: undefined,
    } as any;

    const payload = buildMessagePayload(msg, 123);
    expect(payload.text).toBe("hello");
    expect(payload.chat_id).toBe(123);
    expect(payload.attachments).toBeUndefined();
    expect(payload.reply_to).toBeUndefined();
  });

  it("extracts location attachment", () => {
    const msg = {
      text: undefined,
      caption: undefined,
      photo: undefined,
      location: { latitude: 32.08, longitude: 34.78 },
      venue: undefined,
      reply_to_message: undefined,
      forward_origin: undefined,
    } as any;

    const payload = buildMessagePayload(msg, 123);
    expect(payload.attachments).toHaveLength(1);
    expect(payload.attachments![0]).toEqual({
      type: "location",
      latitude: 32.08,
      longitude: 34.78,
    });
  });

  it("extracts venue attachment with title", () => {
    const msg = {
      text: undefined,
      caption: undefined,
      photo: undefined,
      location: undefined,
      venue: {
        location: { latitude: 32.08, longitude: 34.78 },
        title: "Coffee Shop",
      },
      reply_to_message: undefined,
      forward_origin: undefined,
    } as any;

    const payload = buildMessagePayload(msg, 123);
    expect(payload.attachments).toHaveLength(1);
    expect(payload.attachments![0]).toEqual({
      type: "location",
      latitude: 32.08,
      longitude: 34.78,
      title: "Coffee Shop",
    });
  });

  it("extracts reply context from bot message", () => {
    const msg = {
      text: "yes do it",
      caption: undefined,
      photo: undefined,
      location: undefined,
      venue: undefined,
      reply_to_message: {
        text: "Should I create this task?",
        from: { is_bot: true },
      },
      forward_origin: undefined,
    } as any;

    const payload = buildMessagePayload(msg, 123);
    expect(payload.reply_to).toEqual({
      text: "Should I create this task?",
      from: "assistant",
    });
  });

  it("extracts reply context from user message", () => {
    const msg = {
      text: "what about this?",
      caption: undefined,
      photo: undefined,
      location: undefined,
      venue: undefined,
      reply_to_message: {
        text: "I went for a run",
        from: { is_bot: false },
      },
      forward_origin: undefined,
    } as any;

    const payload = buildMessagePayload(msg, 123);
    expect(payload.reply_to).toEqual({
      text: "I went for a run",
      from: "user",
    });
  });

  it("extracts forward context from user forward", () => {
    const msg = {
      text: "Check this out",
      caption: undefined,
      photo: undefined,
      location: undefined,
      venue: undefined,
      reply_to_message: undefined,
      forward_origin: {
        type: "user",
        sender_user: { first_name: "Alice" },
        date: 1709568000,
      },
    } as any;

    const payload = buildMessagePayload(msg, 123);
    expect(payload.forwarded_from).toEqual({
      from_name: "Alice",
      text: "Check this out",
      date: expect.any(String),
    });
  });

  it("uses caption when text is absent (photo message)", () => {
    const msg = {
      text: undefined,
      caption: "Dog walk photo",
      photo: [
        { file_id: "small", width: 90, height: 90, file_size: 1000 },
        { file_id: "large", width: 800, height: 600, file_size: 50000 },
      ],
      location: undefined,
      venue: undefined,
      reply_to_message: undefined,
      forward_origin: undefined,
    } as any;

    const payload = buildMessagePayload(msg, 123);
    expect(payload.text).toBe("Dog walk photo");
  });
});

const { api } = await import("../../src/api/client.js");
const { messageHandler } = await import("../../src/conversations/message.js");

describe("document attachments", () => {
  function makeDocCtx(document: Record<string, unknown>, caption?: string) {
    const msg = {
      message_id: 1,
      date: 1749500000,
      chat: { id: 123, type: "private" },
      document,
      caption,
    };
    return {
      update: { update_id: 1, message: msg },
      message: msg,
      chat: msg.chat,
      me: { id: 42, is_bot: true, username: "test_bot" },
      replyWithChatAction: vi.fn(),
      reply: vi.fn().mockResolvedValue({ message_id: 2 }),
      api: { editMessageText: vi.fn() },
    } as any;
  }

  beforeEach(() => {
    vi.mocked(api.sendMessage).mockReset().mockResolvedValue({
      intent: "GENERAL_CHAT",
      response: "ok",
    } as any);
  });

  it("downloads an image document and forwards it as a photo attachment", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        json: async () => ({ ok: true, result: { file_path: "documents/file_1.jpg" } }),
      })
      .mockResolvedValueOnce({
        ok: true,
        arrayBuffer: async () => new TextEncoder().encode("img-bytes").buffer,
      });
    vi.stubGlobal("fetch", fetchMock);

    const ctx = makeDocCtx({
      file_id: "doc-file-id",
      file_name: "IMG_1234.jpg",
      mime_type: "image/jpeg",
    });
    await messageHandler.middleware()(ctx, async () => {});

    expect(api.sendMessage).toHaveBeenCalledTimes(1);
    const payload = vi.mocked(api.sendMessage).mock.calls[0]![0] as any;
    expect(payload.attachments).toHaveLength(1);
    expect(payload.attachments[0]).toMatchObject({
      type: "photo",
      filename: "IMG_1234.jpg",
      mime_type: "image/jpeg",
    });
    expect(payload.attachments[0].data).toBe(
      Buffer.from("img-bytes").toString("base64"),
    );
    vi.unstubAllGlobals();
  });

  it("skips non-image documents with a note in the text", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const ctx = makeDocCtx({
      file_id: "doc-file-id",
      file_name: "report.pdf",
      mime_type: "application/pdf",
    });
    await messageHandler.middleware()(ctx, async () => {});

    expect(fetchMock).not.toHaveBeenCalled();
    const payload = vi.mocked(api.sendMessage).mock.calls[0]![0] as any;
    expect(payload.attachments).toBeUndefined();
    expect(payload.text).toContain("[Unsupported file attachment: report.pdf]");
    vi.unstubAllGlobals();
  });
});

describe("answering the bot's own question without a Telegram reply", () => {
  // The reported bug. The bot's gap prompt is a plain ctx.reply and never
  // passes through POST /message, so on 2026-09-12 17:56 "Bar hopping"
  // reached the agent as two words with no interval (the server logged
  // has_reply_to: false) and it asked for times the bot had just named.
  const QUESTION =
    "15:00–17:30 on 2026-09-12 is unaccounted — what was it?";

  beforeEach(async () => {
    const { resetOpenQuestions } = await import("../../src/state/open-question.js");
    resetOpenQuestions();
  });

  it("carries the question as reply context", async () => {
    const { noteOpenQuestion } = await import("../../src/state/open-question.js");
    noteOpenQuestion(123, QUESTION);

    const payload = buildMessagePayload({ text: "Bar hopping" } as never, 123);

    expect(payload.reply_to).toEqual({ text: QUESTION, from: "assistant" });
  });

  it("consumes it, so it cannot ride along on the next message too", async () => {
    const { noteOpenQuestion } = await import("../../src/state/open-question.js");
    noteOpenQuestion(123, QUESTION);

    buildMessagePayload({ text: "Bar hopping" } as never, 123);
    const second = buildMessagePayload({ text: "what's my balance?" } as never, 123);

    expect(second.reply_to).toBeUndefined();
  });

  it("prefers a real reply and drops the pending question", async () => {
    const { noteOpenQuestion, takeOpenQuestion } = await import(
      "../../src/state/open-question.js"
    );
    noteOpenQuestion(123, QUESTION);

    const payload = buildMessagePayload({
      text: "Bar hopping",
      reply_to_message: { text: "something else entirely", from: { is_bot: true } },
    } as never, 123);

    // The explicit reply wins...
    expect(payload.reply_to).toEqual({
      text: "something else entirely", from: "assistant",
    });
    // ...and the question the user did not answer is gone, rather than
    // waiting to attach itself to whatever comes next.
    expect(takeOpenQuestion(123)).toBeUndefined();
  });

  it("adds nothing when the bot has asked nothing", () => {
    const payload = buildMessagePayload({ text: "Bar hopping" } as never, 123);

    expect(payload.reply_to).toBeUndefined();
  });
});

describe("the hints survive the handler's own typing indicator", () => {
  // Written after the fix above failed in production while its unit tests
  // passed. `buildMessagePayload` tested in isolation never sees the typing
  // indicator, and the typing indicator is what destroyed the hint — so the
  // ordering has to be asserted at the handler, with the transformer wired in
  // as it is live.
  it("reads the open question even though typing fires first", async () => {
    const { noteOpenQuestion } = await import("../../src/state/open-question.js");
    const { dropPerMessageHints } = await import("../../src/bot.js");
    const QUESTION = "15:00–17:30 on 2026-09-12 is unaccounted — what was it?";

    (api.sendMessage as any).mockResolvedValue({
      intent: "log", response: "ok", awaiting_confirmation: false,
    });
    noteOpenQuestion(123, QUESTION);

    const msg = {
      message_id: 1,
      date: 1749500000,
      chat: { id: 123, type: "private" },
      text: "Bar hopping",
    };
    const ctx: any = {
      update: { update_id: 1, message: msg },
      message: msg,
      chat: msg.chat,
      me: { id: 42, is_bot: true, username: "test_bot" },
      // The real ctx routes this through bot.api, and so through the
      // transformer. Reproduce that, or the test cannot see the bug.
      replyWithChatAction: async () => {
        await dropPerMessageHints(
          async () => ({ ok: true, result: {} }) as any,
          "sendChatAction",
          { chat_id: 123, action: "typing" } as never,
          undefined,
        );
      },
      reply: vi.fn().mockResolvedValue({ message_id: 2 }),
      api: { editMessageText: vi.fn() },
    };

    await messageHandler.middleware()(ctx, async () => {});

    const payload = (api.sendMessage as any).mock.calls.at(-1)?.[0];
    expect(payload?.reply_to).toEqual({ text: QUESTION, from: "assistant" });
  });
});
