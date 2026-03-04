import type {
  DailyResponse,
  Task,
  Habit,
  Goal,
  TokensResponse,
  CalendarEvent,
  MessageResponse,
  Attachment,
  ReplyContext,
  ForwardContext,
} from "@mazkir/shared-types";

export function createApiClient(baseUrl: string, apiKey: string) {
  async function request<T>(path: string, options?: RequestInit): Promise<T> {
    const res = await fetch(`${baseUrl}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(apiKey ? { "X-API-Key": apiKey } : {}),
        ...options?.headers,
      },
    });
    if (!res.ok) {
      throw new Error(`API error: ${res.status} ${res.statusText}`);
    }
    return res.json() as Promise<T>;
  }

  return {
    // Daily
    getDaily: () => request<DailyResponse>("/daily"),

    // Tasks
    listTasks: () => request<Task[]>("/tasks"),
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
