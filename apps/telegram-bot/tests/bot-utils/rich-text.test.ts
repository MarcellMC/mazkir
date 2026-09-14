import { describe, it, expect } from "vitest";
import {
  richTextToPlain,
  richBlockToPlain,
  repliedToText,
} from "../../src/bot-utils/rich-text.js";

describe("richTextToPlain", () => {
  it("flattens nested formatting to its visible text", () => {
    expect(richTextToPlain([
      { type: "bold", text: "Washing machine" },
      " started at ",
      { type: "italic", text: [{ type: "code", text: "23:55" }] },
    ] as never)).toBe("Washing machine started at 23:55");
  });

  it("uses the leaves that do not carry `text`", () => {
    expect(richTextToPlain([
      { type: "custom_emoji", custom_emoji_id: "1", alternative_text: "🫧" },
      " ",
      { type: "mathematical_expression", expression: "x^2" },
    ] as never)).toBe("🫧 x^2");
  });

  it("drops buttons and anchors", () => {
    expect(richTextToPlain([
      "keep",
      { type: "anchor", name: "a" },
      { type: "button", button: {} },
    ] as never)).toBe("keep");
  });
});

describe("richBlockToPlain", () => {
  it("recurses through lists, quotes and details", () => {
    const list = { type: "list", items: [
      { blocks: [{ type: "paragraph", text: "one" }] },
      { label: "2.", blocks: [{ type: "paragraph", text: "two" }] },
    ] };
    expect(richBlockToPlain(list as never)).toBe("- one\n2. two");

    const details = { type: "details", summary: "More", blocks: [
      { type: "blockquote", blocks: [{ type: "paragraph", text: "inside" }] },
    ] };
    expect(richBlockToPlain(details as never)).toBe("More\ninside");
  });

  it("reads a table row by row", () => {
    const table = { type: "table", cells: [
      [{ text: "✓ 23:45–23:55" }, { text: "Washing machine" }],
    ] };
    expect(richBlockToPlain(table as never)).toBe("✓ 23:45–23:55 | Washing machine");
  });

  it("keeps a photo's caption and nothing else", () => {
    expect(richBlockToPlain({
      type: "photo", photo: [], caption: { text: "the laundry" },
    } as never)).toBe("the laundry");
  });

  it("yields empty text for a block type it does not know", () => {
    // A Bot API addition must shorten the reply context, not throw and lose
    // the reply.
    expect(richBlockToPlain({ type: "hologram" } as never)).toBe("");
  });
});

describe("repliedToText", () => {
  const richAgentReply = {
    message_id: 7,
    from: { is_bot: true },
    rich_message: { blocks: [
      { type: "paragraph", text: [
        "🫧 ", { type: "bold", text: "Washing machine" },
        " started at 23:55. I'll leave the end open — let me know when it's done!",
      ] },
    ] },
  };

  it("reads a reply to a rich agent message, which has no .text", () => {
    // The 2026-09-15 case.
    expect(repliedToText({ text: "x", reply_to_message: richAgentReply } as never))
      .toBe("🫧 Washing machine started at 23:55. I'll leave the end open — let me know when it's done!");
  });

  it("still reads plain text and captions", () => {
    expect(repliedToText({ reply_to_message: { text: "plain" } } as never)).toBe("plain");
    expect(repliedToText({ reply_to_message: { caption: "cap" } } as never)).toBe("cap");
  });

  it("prefers the part the user quoted", () => {
    expect(repliedToText({
      quote: { text: "Washing machine", position: 3 },
      reply_to_message: richAgentReply,
    } as never)).toBe("Washing machine");
  });

  it("is empty when there is no reply or nothing readable in it", () => {
    expect(repliedToText({ text: "x" } as never)).toBe("");
    expect(repliedToText({ reply_to_message: { sticker: {} } } as never)).toBe("");
  });
});
