import type {
  DailyResponse,
  Task,
  TaskDetail,
  Habit,
  Goal,
  TokensResponse,
  CalendarEvent,
  MessageResponse,
  Attachment,
  ReplyContext,
  ForwardContext,
} from "@mazkir/shared-types";

import { logger } from "../logger.js";

export interface StreamMessagePayload {
  text: string;
  chat_id: number;
  attachments?: Attachment[];
  reply_to?: ReplyContext;
  forwarded_from?: ForwardContext;
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
        throw new Error(`API error: ${res.status} ${res.statusText}`);
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
    getDaily: () => request<DailyResponse>("/daily"),

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
  onChunk: (text: string) => void,
  baseUrl: string = config.vaultServerUrl,
  apiKey: string = config.vaultServerApiKey,
): Promise<MessageResponse> {
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
        onChunk(data["text"]);
      }
    }
  }

  if (!final) {
    throw new Error("SSE stream ended without final payload");
  }
  return final;
}
