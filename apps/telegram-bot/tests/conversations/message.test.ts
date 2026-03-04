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
