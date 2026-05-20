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
