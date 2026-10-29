import type { Receipt, ReceiptLine } from "@mazkir/shared-types";
import { describe, it, expect } from "vitest";
import { buildReceiptRich } from "../../src/formatters/receipt-rich.js";

const receipt: Receipt = {
  turn_id: "t0000beef",
  lines: [
    { id: 0, glyph: "✓", when: "yest 23:15–23:35", text: "Dog walk", detail: "🎯 Dog Walk 2/2 · +5 🪙 · streak 6",
      sync: "⏳ calendar", reason: "", status: "done",
      buttons: [{ label: "✎", data: "block:edit:2026-09-27:evt_1" }] },
    { id: 1, glyph: "?", when: "", text: "A <b>match</b>", detail: null, sync: null, reason: "no time given",
      status: "question", buttons: [] },
  ],
  undo: "rcpt:t0000beef:u:un",
  open_question: "A match · no time given. Reply with one.",
  text: "",
};

const html = (r: Receipt) => buildReceiptRich(r).html ?? "";
const line = (over: Partial<ReceiptLine>): ReceiptLine => ({ ...receipt.lines[1]!, ...over });
const withLines = (...lines: ReceiptLine[]): Receipt => ({ ...receipt, lines, undo: null, open_question: null });

describe("buildReceiptRich", () => {
  it("draws each line with its glyph, time, text, details and buttons", () => {
    const out = html(receipt);
    expect(out).toContain("<td>✓ yest 23:15–23:35</td>");
    expect(out).toContain("Dog walk <sub>🎯 Dog Walk 2/2 · +5 🪙 · streak 6</sub> <sub>⏳ calendar</sub>");
    expect(out).toContain('<td><tg-button-row><tg-button type="callback_data" data="block:edit:2026-09-27:evt_1">✎</tg-button></tg-button-row></td>');
  });

  it("escapes what the user wrote", () => {
    expect(html(receipt)).toContain("A &lt;b&gt;match&lt;/b&gt; <sub>no time given</sub>");
  });

  it("escapes &, <, > in text, reason, detail, sync, when, glyph and the open question", () => {
    const out = html({
      ...withLines(line({ text: "a & b", reason: "x < y", detail: "p > q", sync: "<s>", when: "<w>", glyph: "<g>" })),
      open_question: "what <i>& when?",
    });
    for (const raw of ["a & b", "x < y", "p > q", "<s>", "<w>", "<g>", "<i>&"]) expect(out).not.toContain(raw);
    expect(out).toContain("a &amp; b");
    expect(out).toContain("<sub>x &lt; y</sub>");
    expect(out).toContain("<sub>p &gt; q</sub>");
    expect(out).toContain("&lt;w&gt;");
    expect(out).toContain("what &lt;i&gt;&amp; when?");
  });

  it("escapes quotes in data attributes and labels in buttons", () => {
    const out = html(withLines(line({ buttons: [{ label: 'a"<b>&', data: 'x"y\'z<&' }] })));
    expect(out).toContain('data="x&quot;y&#39;z&lt;&amp;"');
    expect(out).toContain(">a\"&lt;b&gt;&amp;</tg-button>");
  });

  it("offers Undo only while the server does", () => {
    expect(html(receipt)).toContain('data="rcpt:t0000beef:u:un">Undo</tg-button>');
    expect(html({ ...receipt, undo: null })).not.toContain("Undo");
  });

  it("renders the open question as the reply prompt", () => {
    expect(html(receipt)).toContain("<p><i>A match · no time given. Reply with one.</i></p>");
    expect(html({ ...receipt, open_question: null })).not.toContain("<i>");
  });

  it("never emits an empty button row", () => {
    const out = html(withLines(line({ buttons: [] })));
    expect(out).not.toContain("<tg-button-row></tg-button-row>");
    expect(out).not.toContain("<tg-button-row>");
  });

  it("caps a row at 8 buttons", () => {
    const buttons = Array.from({ length: 10 }, (_, i) => ({ label: `${i}`, data: `d:${i}` }));
    const out = html(withLines(line({ buttons })));
    expect(out.match(/<tg-button /g)).toHaveLength(8);
  });

  it("drops a button whose data Telegram would reject, rather than truncating it", () => {
    const long = "x".repeat(65);
    const ok = "y".repeat(64);
    const out = html(withLines(line({ buttons: [{ label: "A", data: long }, { label: "B", data: ok }] })));
    expect(out).not.toContain(long);
    expect(out).toContain(`data="${ok}">B<`);
    // multibyte counts in bytes, not characters
    const wide = html(withLines(line({ buttons: [{ label: "A", data: "é".repeat(33) }] })));
    expect(wide).not.toContain("<tg-button");
    expect(wide).not.toContain("<tg-button-row>");
  });

  it("drops an over-long Undo", () => {
    expect(html({ ...receipt, undo: "u".repeat(65) })).not.toContain("Undo");
  });

  it("falls back to the receipt text when there are no lines", () => {
    const out = html({ turn_id: "t", lines: [], undo: null, open_question: null, text: "Nothing <logged> & done" });
    expect(out).toBe("<p>Nothing &lt;logged&gt; &amp; done</p>");
  });

  it("renders something for a wholly empty receipt", () => {
    expect(html({ turn_id: "t", lines: [], undo: null, open_question: null, text: "" })).toBe("<p>—</p>");
  });
});
