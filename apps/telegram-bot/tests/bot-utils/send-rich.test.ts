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
