export type Intent =
  | "HABIT_COMPLETION"
  | "HABIT_CREATION"
  | "TASK_CREATION"
  | "TASK_COMPLETION"
  | "GOAL_CREATION"
  | "QUERY"
  | "GENERAL_CHAT";

export interface Attachment {
  type: "photo" | "location";
  /** base64-encoded image bytes (photo only) */
  data?: string;
  /** MIME type, e.g. "image/jpeg" (photo only) */
  mime_type?: string;
  /** e.g. "photo_2026-03-04_14-30.jpg" (photo only) */
  filename?: string;
  /** Location fields */
  latitude?: number;
  longitude?: number;
  /** Venue name if sent as venue */
  title?: string;
}

export interface ReplyContext {
  /** Text of the message being replied to */
  text: string;
  /** Whether the original was from user or assistant (bot) */
  from: "user" | "assistant";
}

export interface ForwardContext {
  /** Name of the original sender/channel */
  from_name: string;
  /** Text content of the forwarded message */
  text: string;
  /** Original message date ISO string */
  date?: string;
}

export interface MessageRequest {
  text: string;
  chat_id: number;
  attachments?: Attachment[];
  reply_to?: ReplyContext;
  forwarded_from?: ForwardContext;
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
