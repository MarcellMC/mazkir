import type {
  DailyResponse,
  Task,
  TaskDetail,
  Habit,
  Goal,
  GoalDetail,
  TokensResponse,
  CalendarEvent,
  MessageResponse,
  Attachment,
  ReplyContext,
  ForwardContext,
  Receipt,
  ReceiptUpdate,
  ReceiptActionResponse,
} from "@mazkir/shared-types";

import { logger } from "../logger.js";

export interface StreamMessagePayload {
  text: string;
  chat_id: number;
  selected_date?: string;
  attachments?: Attachment[];
  reply_to?: ReplyContext;
  forwarded_from?: ForwardContext;
  message_id?: number;
}

/** What a streamed reply can carry besides text (fast-lane spec §8.1). */
export interface StreamHandlers {
  onChunk: (text: string) => void | Promise<void>;
  onStage?: (stage: string) => void | Promise<void>;
  onReceipt?: (receipt: Receipt) => void | Promise<void>;
  onReceiptUpdate?: (update: ReceiptUpdate) => void | Promise<void>;
}

/** A non-2xx answer from vault-server; the message text is unchanged. */
export class ApiError extends Error {
  constructor(readonly status: number, statusText: string) {
    super(`API error: ${status} ${statusText}`);
    this.name = "ApiError";
  }
}

/** Run one stream handler; a handler that throws (a failed Telegram edit) must
 *  not lose the rest of the stream or its final payload. */
async function safely(name: string, fn: (() => void | Promise<void>) | undefined): Promise<void> {
  if (!fn) return;
  try {
    await fn();
  } catch (err) {
    logger.warn({ event_type: "stream_handler_error", handler: name, err: String(err) }, "stream_handler_error");
  }
}

export function createApiClient(baseUrl: string, apiKey: string) {
  async function request<T>(path: string, options?: RequestInit): Promise<T> {
    const method = options?.method ?? "GET";
    const start = Date.now();
    try {
      const res = await fetch(`${baseUrl}${path}`, {
        ...options,
        headers: {
          "Content-Type": "application/json",
          ...(apiKey ? { "X-API-Key": apiKey } : {}),
          ...options?.headers,
        },
      });
      const duration_ms = Date.now() - start;
      logger.info(
        {
          event_type: "api_call",
          method,
          path,
          status: res.status,
          ok: res.ok,
          duration_ms,
        },
        "api_call",
      );
      if (!res.ok) {
        throw new ApiError(res.status, res.statusText);
      }
      return res.json() as Promise<T>;
    } catch (err) {
      const duration_ms = Date.now() - start;
      logger.error(
        {
          event_type: "api_call",
          method,
          path,
          status: "error",
          duration_ms,
          err: String(err),
        },
        "api_call_error",
      );
      throw err;
    }
  }

  return {
    // Daily
    getDaily: (date?: string) =>
      request<DailyResponse>(date ? `/daily?date=${date}` : "/daily"),

    setBlockState: (date: string, eventId: string, state: "approved" | "dismissed") =>
      request<{
        ok: boolean; state: string; event_id: string;
        habit: { name: string; tokens_earned: number; new_streak: number } | null;
        checkbox: { text: string } | null;
      }>(`/events/${date}/${eventId}/state`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ state }),
      }),

    approveAll: (date: string) =>
      request<{
        ok: boolean;
        approved: { event_id: string; name: string; was_guess: boolean }[];
        failed: { event_id: string; reason: string }[];
      }>(`/daily/${date}/approve-all`, { method: "POST" }),

    fillGap: (date: string, start: string, end: string, name?: string) =>
      request<{ ok: boolean; event_id: string; name: string; was_guess: boolean }>(
        `/daily/${date}/gaps/fill`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ start, end, name: name ?? null }),
        },
      ),

    patchEvent: (date: string, eventId: string, body: Record<string, unknown>) =>
      request<Record<string, unknown>>(`/events/${date}/${eventId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),

    deleteEvent: (date: string, eventId: string) =>
      request<{ ok: boolean; deleted: string; calendar_sync: Record<string, unknown> }>(
        `/events/${date}/${eventId}`,
        { method: "DELETE" },
      ),

    cancelEvent: (date: string, eventId: string) =>
      request<{ ok: boolean; cancelled: string; calendar_sync: Record<string, unknown> }>(
        `/events/${date}/${eventId}/cancel`,
        { method: "POST" },
      ),

    // Tasks
    listTasks: () => request<Task[]>("/tasks"),
    getTask: (slug: string) =>
      request<TaskDetail>(`/tasks/${encodeURIComponent(slug)}`),
    createTask: (data: Record<string, unknown>) =>
      request<Task>("/tasks", { method: "POST", body: JSON.stringify(data) }),
    completeTask: (name: string) =>
      request<unknown>(`/tasks/${encodeURIComponent(name)}`, {
        method: "PATCH",
        body: JSON.stringify({ completed: true }),
      }),

    // Habits
    listHabits: () => request<Habit[]>("/habits"),
    createHabit: (data: Record<string, unknown>) =>
      request<Habit>("/habits", { method: "POST", body: JSON.stringify(data) }),
    completeHabit: (name: string) =>
      request<unknown>(`/habits/${encodeURIComponent(name)}`, {
        method: "PATCH",
        body: JSON.stringify({ completed: true }),
      }),

    // Goals
    listGoals: () => request<Goal[]>("/goals"),
    getGoal: (slug: string) =>
      request<GoalDetail>(`/goals/${encodeURIComponent(slug)}`),
    createGoal: (data: Record<string, unknown>) =>
      request<Goal>("/goals", { method: "POST", body: JSON.stringify(data) }),

    // Tokens
    getTokens: () => request<TokensResponse>("/tokens"),

    // Calendar
    getCalendarEvents: () => request<CalendarEvent[]>("/calendar/events"),
    syncCalendar: () =>
      request<Record<string, unknown>>("/calendar/sync", { method: "POST" }),

    // Message (NL)
    sendMessage: (payload: {
      text: string;
      chat_id: number;
      attachments?: Attachment[];
      reply_to?: ReplyContext;
      forwarded_from?: ForwardContext;
    }) =>
      request<MessageResponse>("/message", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    sendConfirmation: (chatId: number, actionId: string, response: string) =>
      request<MessageResponse>("/message/confirm", {
        method: "POST",
        body: JSON.stringify({
          chat_id: chatId,
          action_id: actionId,
          response,
        }),
      }),
    // A tap on a fast-lane receipt (spec §8.2): the server acts and re-renders.
    receiptAction: (turnId: string, line: string, action: string) =>
      request<ReceiptActionResponse>(`/fast/receipts/${encodeURIComponent(turnId)}/${encodeURIComponent(line)}/${encodeURIComponent(action)}`, { method: "POST" }),
  };
}

import { config } from "../config.js";

export const api = createApiClient(config.vaultServerUrl, config.vaultServerApiKey);

/**
 * Stream a message via SSE. Calls `onChunk` for each partial text chunk, then
 * resolves with the final MessageResponse when the stream ends.
 */
export async function streamMessage(
  payload: StreamMessagePayload,
  handlers: StreamHandlers | ((text: string) => void),
  baseUrl: string = config.vaultServerUrl,
  apiKey: string = config.vaultServerApiKey,
): Promise<MessageResponse> {
  const h: StreamHandlers = typeof handlers === "function" ? { onChunk: handlers } : handlers;
  const url = `${baseUrl}/message?stream=true`;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "text/event-stream",
    ...(apiKey ? { "X-API-Key": apiKey } : {}),
  };

  const res = await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
  });

  if (!res.ok || !res.body) {
    throw new Error(`SSE stream failed: ${res.status} ${res.statusText}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let final: MessageResponse | null = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const event = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const line = event.trim();
      if (!line.startsWith("data: ")) continue;
      const data = JSON.parse(line.slice(6)) as Record<string, unknown>;
      if (data["done"] === true) {
        final = data["response"] as MessageResponse;
      } else if (typeof data["text"] === "string") {
        const t = data["text"];
        await safely("onChunk", () => h.onChunk(t));
      } else if (typeof data["stage"] === "string") {
        const s = data["stage"];
        await safely("onStage", h.onStage && (() => h.onStage!(s)));
      } else if (data["receipt"]) {
        const r = data["receipt"] as Receipt;
        await safely("onReceipt", h.onReceipt && (() => h.onReceipt!(r)));
      } else if (data["receipt_update"]) {
        const u = data["receipt_update"] as ReceiptUpdate;
        await safely("onReceiptUpdate", h.onReceiptUpdate && (() => h.onReceiptUpdate!(u)));
      }
    }
  }

  if (!final) {
    throw new Error("SSE stream ended without final payload");
  }
  return final;
}
