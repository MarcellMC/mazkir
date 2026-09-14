import type { Message, RichBlock, RichText } from "@grammyjs/types";

/** Plain text of a `RichText` value — the inline layer of a rich message.
 *
 *  Formatting wrappers (bold, links, mentions, …) all carry their visible
 *  content in `text`, so they recurse. The few leaves that do not are handled
 *  by name: a custom emoji's `alternative_text`, a formula's `expression`.
 *  Buttons and anchors contribute nothing a reader would quote. */
export function richTextToPlain(t: RichText | undefined): string {
  if (t === undefined || t === null) return "";
  if (typeof t === "string") return t;
  if (Array.isArray(t)) return t.map(richTextToPlain).join("");
  switch (t.type) {
    case "custom_emoji":
      return t.alternative_text;
    case "mathematical_expression":
      return t.expression;
    case "button":
    case "anchor":
      return "";
    default:
      return "text" in t ? richTextToPlain(t.text) : "";
  }
}

function blocksToPlain(blocks: RichBlock[] | undefined): string {
  return (blocks ?? []).map(richBlockToPlain).filter(Boolean).join("\n");
}

function caption(c: { text?: RichText } | undefined): string {
  return c ? richTextToPlain(c.text) : "";
}

/** Plain text of one rich block, recursing through containers.
 *
 *  Media keep only their caption and buttons contribute nothing: the point is
 *  what a person reading the message would say it *said*. An unknown block
 *  type yields "" rather than throwing, so a Bot API addition degrades to a
 *  slightly shorter reply context instead of dropping the reply. */
export function richBlockToPlain(b: RichBlock): string {
  switch (b.type) {
    case "paragraph":
    case "heading":
    case "pre":
    case "footer":
    case "thinking":
      return richTextToPlain(b.text);
    case "pullquote":
    case "expandable_blockquote":
      return richTextToPlain(b.text);
    case "mathematical_expression":
      return b.expression;
    case "list":
      return b.items
        .map((item) => {
          const body = blocksToPlain(item.blocks);
          return item.label ? `${item.label} ${body}` : `- ${body}`;
        })
        .join("\n");
    case "blockquote":
    case "collage":
    case "slideshow":
      return blocksToPlain(b.blocks);
    case "details":
      return [richTextToPlain(b.summary), blocksToPlain(b.blocks)]
        .filter(Boolean)
        .join("\n");
    case "table":
      return b.cells
        .map((row) => row.map((cell) => richTextToPlain(cell.text)).join(" | "))
        .join("\n");
    case "map":
    case "animation":
    case "audio":
    case "document":
    case "photo":
    case "video":
    case "voice_note":
      return caption(b.caption);
    case "divider":
    case "anchor":
    case "buttons":
      return "";
    default:
      return "";
  }
}

/** The text a reply is answering, whatever kind of message it was.
 *
 *  Agent answers and the `/day`, `/tasks`, `/habits` and `/goals` views are
 *  sent as rich messages, which carry `rich_message.blocks` and no `.text`.
 *  Reading only `.text` made every reply to an agent answer arrive with no
 *  context — `reply_to_source: "none"` on 2026-09-15, when "record it between
 *  23:45 and 23:55 instead" answered a washing-machine message and the agent
 *  had to ask which block. It had been that way since agent replies became
 *  rich on 2026-06-19; only replies to plain-text bot messages (the gap
 *  prompts) ever carried context, which is why it looked like a regression.
 *
 *  A Telegram quote — the part of the message the user selected — wins over
 *  the whole message, because it is the more specific statement of what they
 *  meant. Returns "" when the replied-to message has nothing readable. */
export function repliedToText(msg: Message): string {
  const quoted = msg.quote?.text?.trim();
  if (quoted) return quoted;
  const target = msg.reply_to_message;
  if (!target) return "";
  if (target.text) return target.text;
  if (target.caption) return target.caption;
  const rich = (target as { rich_message?: { blocks?: RichBlock[] } }).rich_message;
  if (rich?.blocks) return blocksToPlain(rich.blocks).replace(/\n{3,}/g, "\n\n").trim();
  return "";
}
