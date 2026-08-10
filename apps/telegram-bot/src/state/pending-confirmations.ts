/**
 * Which confirmation, if any, each chat currently owes an answer to.
 *
 * Shared deliberately: a confirmation can be answered two ways — by typing
 * (the text handler in conversations/message.ts) or by tapping a button
 * (the callback handler in callbacks/index.ts). Both must see the same
 * state. When only the text path cleared it, answering by button left the
 * entry behind and the user's *next* message was swallowed as a reply to
 * an action the server had already consumed, surfacing as
 * "No pending action found."
 *
 * In-memory by design: a pending confirmation is a property of the current
 * conversation, and the server's own PendingAction store is in-memory too,
 * so both are dropped together on restart.
 */
const pending = new Map<number, string>();

export function getPendingConfirmation(chatId: number): string | undefined {
  return pending.get(chatId);
}

export function setPendingConfirmation(chatId: number, actionId: string): void {
  pending.set(chatId, actionId);
}

export function clearPendingConfirmation(chatId: number): void {
  pending.delete(chatId);
}
