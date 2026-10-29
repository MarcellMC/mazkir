import type { InputFile } from "grammy";
import type { InputRichMessage } from "@grammyjs/types";
import type { Receipt, ReceiptButton, ReceiptLine } from "@mazkir/shared-types";
import { escapeHtml } from "./telegram.js";

/** A fast-lane receipt (spec §8.2) as a rich message. The server decides every
 *  word, glyph and button; this only draws them, so a rule changes in one
 *  place. Buttons live in table cells: the one place Telegram renders them
 *  as compact pills rather than full-width bars (see day-rich.ts's
 *  `cellButtons`). Everything a user wrote is escaped. */

/** Telegram allows 1-8 buttons per row and 64 bytes of callback data. */
const MAX_BUTTONS_PER_ROW = 8;
const MAX_CALLBACK_BYTES = 64;

/** escapeHtml leaves quotes alone, which is fine in text but would end an
 *  attribute early. */
function escapeAttr(text: string): string {
  return escapeHtml(text).replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}

/** A button whose data Telegram would reject is dropped, not truncated: a
 *  truncated payload would address the wrong action. */
function drawable(b: ReceiptButton): boolean {
  const bytes = Buffer.byteLength(b.data, "utf8");
  return bytes > 0 && bytes <= MAX_CALLBACK_BYTES && b.label.length > 0;
}

function button(b: ReceiptButton): string {
  return `<tg-button type="callback_data" data="${escapeAttr(b.data)}">${escapeHtml(b.label)}</tg-button>`;
}

function cell(buttons: ReceiptButton[]): string {
  const shown = buttons.filter(drawable).slice(0, MAX_BUTTONS_PER_ROW);
  return shown.length
    ? `<td><tg-button-row>${shown.map(button).join("")}</tg-button-row></td>`
    : "<td></td>";
}

function row(line: ReceiptLine): string {
  const when = line.when ? ` ${escapeHtml(line.when)}` : "";
  const subs = [line.detail, line.sync, line.reason]
    .filter((s): s is string => Boolean(s))
    .map((s) => ` <sub>${escapeHtml(s)}</sub>`)
    .join("");
  return `<tr><td>${escapeHtml(line.glyph)}${when}</td><td>${escapeHtml(line.text)}${subs}</td>${cell(line.buttons)}</tr>`;
}

export function buildReceiptRich(receipt: Receipt): InputRichMessage<InputFile> {
  const parts: string[] = [];
  if (receipt.lines.length) {
    parts.push(`<table>${receipt.lines.map(row).join("")}</table>`);
  } else if (receipt.text) {
    // No lines to draw (empty receipt, or the NO_RECEIPT fallback): the
    // server's plain text is still the answer.
    parts.push(`<p>${escapeHtml(receipt.text)}</p>`);
  }
  if (receipt.open_question) parts.push(`<p><i>${escapeHtml(receipt.open_question)}</i></p>`);
  if (receipt.undo && drawable({ label: "Undo", data: receipt.undo })) {
    parts.push(`<table><tr>${cell([{ label: "Undo", data: receipt.undo }])}</tr></table>`);
  }
  return { html: parts.length ? parts.join("") : "<p>—</p>" };
}
