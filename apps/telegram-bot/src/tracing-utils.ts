import { trace, SpanStatusCode } from "@opentelemetry/api";

/**
 * Record an exception on the currently-active span and mark it ERROR.
 * Use inside a catch block when the error is handled (no re-throw) but
 * the request still failed from an observability standpoint.
 */
export function markActiveSpanError(err: unknown): void {
  const span = trace.getActiveSpan();
  if (!span) return;
  const message = err instanceof Error ? err.message : String(err);
  span.recordException(err instanceof Error ? err : new Error(message));
  span.setStatus({ code: SpanStatusCode.ERROR, message });
}

/**
 * Set OpenInference `output.value` on the currently-active span so Phoenix
 * displays the user-facing reply alongside the input in the trace UI.
 */
export function setActiveSpanOutput(value: string): void {
  const span = trace.getActiveSpan();
  if (!span) return;
  span.setAttribute("output.value", value);
  span.setAttribute("output.mime_type", "text/plain");
}

/** Where a message's reply context came from, if anywhere.
 *
 *  `"telegram"` — the user used Telegram's reply-to.
 *  `"open_question"` — the bot asked something one turn ago and supplied it
 *    on the user's behalf (state/open-question.ts).
 *  `"none"` — the turn carried no reply context at all.
 *
 *  The three are worth distinguishing because they fail differently: "none"
 *  when a question was pending means the hint was lost, which is what
 *  happened twice on 2026-09-12.
 */
export type ReplyToSource = "telegram" | "open_question" | "none";

/**
 * Record what context this turn is being sent with, on the active
 * `telegram.update` span.
 *
 * The server stamps the mirror image of this (`set_payload_provenance` in
 * `services/tracing_helpers.py`) from what actually arrived. Read together
 * they say which side of the wire lost something: both "none" means the bot
 * never had it, a disagreement means it was dropped in transit or in
 * serialisation.
 *
 * Exists because Phoenix could not answer "did the gap question reach the
 * agent?" — 30 spans for the failing minute recorded neither the reply
 * context nor the selected date, so the answer had to come from grepping
 * structured logs by timestamp.
 *
 * No-ops without an active span.
 */
export function setPayloadProvenance(p: {
  replyToSource: ReplyToSource;
  selectedDate?: string;
  attachmentCount: number;
  hasForwardedFrom: boolean;
}): void {
  const span = trace.getActiveSpan();
  if (!span) return;
  span.setAttribute("mazkir.payload.reply_to_source", p.replyToSource);
  // Empty string rather than an omitted key, matching the server: a Phoenix
  // filter can then tell "no date was sent" from "this span predates the
  // attribute".
  span.setAttribute("mazkir.payload.selected_date", p.selectedDate ?? "");
  span.setAttribute("mazkir.payload.attachment_count", p.attachmentCount);
  span.setAttribute("mazkir.payload.has_forwarded_from", p.hasForwardedFrom);
}
