/** A fast-lane receipt (fast-lane spec §8.2). The server decides every word,
 *  glyph and button; the bot only draws them. */
export interface ReceiptButton {
  label: string;
  /** `rcpt:<turn>:<line>:<action>`, or `block:edit:<date>:<id>` for ✎. */
  data: string;
}

export interface ReceiptLine {
  id: number;
  /** ✓ fact · ◌ plan · ● proposal · ? question · ✗ failed · ↶ undone · ✕ dismissed */
  glyph: string;
  when: string;
  text: string;
  detail: string | null;
  sync: string | null;
  reason: string;
  status: string;
  buttons: ReceiptButton[];
}

export interface Receipt {
  turn_id: string;
  lines: ReceiptLine[];
  /** Callback data for the turn's Undo; null once nothing can be undone. */
  undo: string | null;
  /** A question to hold for the next message (the bot's open-question hint). */
  open_question: string | null;
  /** The receipt as plain lines: the fallback when a rich message is refused. */
  text: string;
}

export interface ReceiptUpdate {
  line_id: number;
  receipt: Receipt;
}

export interface ReceiptActionResponse {
  receipt: Receipt;
  toast: string;
}
