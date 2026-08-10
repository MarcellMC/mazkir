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
