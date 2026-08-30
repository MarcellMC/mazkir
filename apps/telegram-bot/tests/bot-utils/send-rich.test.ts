import { describe, it, expect, vi } from "vitest";
import { sendRich, richToPlainText } from "../../src/bot-utils/send-rich.js";

function fakeCtx() {
  return {
    replyWithRichMessage: vi.fn().mockResolvedValue({ message_id: 1 }),
    reply: vi.fn().mockResolvedValue({ message_id: 2 }),
  };
}

describe("richToPlainText", () => {
  it("strips html tags and decodes basic entities", () => {
    expect(richToPlainText({ html: "<h2>Tokens</h2><b>42</b> &amp; up" }))
      .toBe("Tokens 42 & up");
  });
  it("returns markdown text as-is", () => {
    expect(richToPlainText({ markdown: "## Hi\n- a" })).toContain("Hi");
  });
});

describe("sendRich", () => {
  it("sends the rich message when the API succeeds", async () => {
    const ctx = fakeCtx();
    await sendRich(ctx as any, { html: "<b>hi</b>" });
    expect(ctx.replyWithRichMessage).toHaveBeenCalledOnce();
    expect(ctx.reply).not.toHaveBeenCalled();
  });
  it("falls back to plain text when the rich send throws", async () => {
    const ctx = fakeCtx();
    ctx.replyWithRichMessage.mockRejectedValueOnce(new Error("bad block"));
    await sendRich(ctx as any, { html: "<h2>T</h2>a &amp; b" });
    expect(ctx.reply).toHaveBeenCalledOnce();
    expect(ctx.reply.mock.calls[0][0]).toBe("T a & b");
  });
});

describe("sendRich fallback", () => {
  it("keeps reply_markup when the rich payload is rejected", async () => {
    const ctx = fakeCtx();
    ctx.replyWithRichMessage.mockRejectedValueOnce(new Error("rich rejected"));
    const extra = {
      reply_markup: { inline_keyboard: [[{ text: "Autonomous", callback_data: "x" }]] },
    };

    await sendRich(ctx as any, { markdown: "pick a lane" }, extra);

    expect(ctx.reply).toHaveBeenCalledOnce();
    expect(ctx.reply.mock.calls[0][1]).toEqual(extra);
  });

  it("still sends the text when there is no extra", async () => {
    const ctx = fakeCtx();
    ctx.replyWithRichMessage.mockRejectedValueOnce(new Error("rich rejected"));

    await sendRich(ctx as any, { markdown: "hello" });

    expect(ctx.reply).toHaveBeenCalledOnce();
    expect(ctx.reply.mock.calls[0][0]).toContain("hello");
  });
});

describe("editRich", () => {
  it("edits the message in place with rich content", async () => {
    const editMessageText = vi.fn().mockResolvedValue(true);
    const ctx = { editMessageText } as never;
    const { editRich } = await import("../../src/bot-utils/send-rich.js");
    await editRich(ctx, { html: "<p>hi</p>" });
    expect(editMessageText).toHaveBeenCalledWith({ html: "<p>hi</p>" });
  });

  it("falls back to plain text when the rich payload is rejected", async () => {
    const editMessageText = vi.fn()
      .mockRejectedValueOnce(new Error("rich rejected"))
      .mockResolvedValue(true);
    const ctx = { editMessageText } as never;
    const { editRich } = await import("../../src/bot-utils/send-rich.js");
    await editRich(ctx, { html: "<p>hi &amp; bye</p>" });
    expect(editMessageText).toHaveBeenLastCalledWith("hi & bye");
  });

  it("treats an unchanged message as success, not a failed payload", async () => {
    // Re-tapping the highlighted day sends identical content. Telegram rejects
    // that, and routing it through the fallback would replace the rich message
    // with plain text — permanently removing the in-body navigation buttons.
    const err = Object.assign(new Error("Bad Request: message is not modified"), {
      description: "Bad Request: message is not modified",
    });
    const editMessageText = vi.fn().mockRejectedValueOnce(err);
    const ctx = { editMessageText } as never;
    const { editRich } = await import("../../src/bot-utils/send-rich.js");
    await editRich(ctx, { html: "<p>same</p>" });
    expect(editMessageText).toHaveBeenCalledTimes(1);  // no fallback attempt
  });

  it("still degrades to plain text on a genuine rejection", async () => {
    const editMessageText = vi.fn()
      .mockRejectedValueOnce(Object.assign(new Error("Bad Request: can't parse entities"), {
        description: "Bad Request: can't parse entities",
      }))
      .mockResolvedValue(true);
    const ctx = { editMessageText } as never;
    const { editRich } = await import("../../src/bot-utils/send-rich.js");
    await editRich(ctx, { html: "<p>hi &amp; bye</p>" });
    expect(editMessageText).toHaveBeenLastCalledWith("hi & bye");
  });

  it("passes extra (e.g. reply_markup) through on the success path", async () => {
    const editMessageText = vi.fn().mockResolvedValue(true);
    const ctx = { editMessageText } as never;
    const { editRich } = await import("../../src/bot-utils/send-rich.js");
    const extra = { reply_markup: { inline_keyboard: [[{ text: "Tasks", callback_data: "nav:tasks" }]] } };

    await editRich(ctx, { html: "<p>hi</p>" }, extra);

    expect(editMessageText).toHaveBeenCalledWith({ html: "<p>hi</p>" }, extra);
  });

  it("passes extra through on the plain-text fallback too", async () => {
    // Same reasoning as sendRich's fallback: dropping `extra` here would
    // strip the keyboard from the degraded message, leaving a prompt the
    // user cannot answer.
    const editMessageText = vi.fn()
      .mockRejectedValueOnce(Object.assign(new Error("Bad Request: can't parse entities"), {
        description: "Bad Request: can't parse entities",
      }))
      .mockResolvedValue(true);
    const ctx = { editMessageText } as never;
    const { editRich } = await import("../../src/bot-utils/send-rich.js");
    const extra = { reply_markup: { inline_keyboard: [[{ text: "Tasks", callback_data: "nav:tasks" }]] } };

    await editRich(ctx, { html: "<p>hi &amp; bye</p>" }, extra);

    expect(editMessageText).toHaveBeenLastCalledWith("hi & bye", extra);
  });
});
