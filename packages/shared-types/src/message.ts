export type Intent =
  | "HABIT_COMPLETION"
  | "HABIT_CREATION"
  | "TASK_CREATION"
  | "TASK_COMPLETION"
  | "GOAL_CREATION"
  | "QUERY"
  | "GENERAL_CHAT";

export interface MessageRequest {
  text: string;
  chat_id: number;
}

export interface MessageResponse {
  intent: Intent;
  response: string;
  data?: Record<string, unknown>;
  awaiting_confirmation?: boolean;
  pending_action_id?: string;
}

export interface ConfirmationRequest {
  chat_id: number;
  action_id: string;
  response: string;
}
