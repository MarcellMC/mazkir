/**
 * The latest unsaved nudge, so text typed after it edits both (location trips
 * spec §6.4).
 *
 * The block-edit pad keeps its draft in callback data (`adj:<date>:<id>:…`),
 * so nothing is written until Save — and text typed after nudging knew
 * nothing of it. "Nudge to 07:25, then type 'that was a run'" means one edit
 * of both the times and the activity, so the bot remembers the drafted times
 * and hands them to the agent with the next message, as reply context.
 *
 * One-shot and short-lived like `open-question.ts`. Unlike the open question
 * it is NOT cleared by every send (bot.ts `dropPerMessageHints`): a trip
 * message arriving meanwhile says nothing about your edit. It ends with an
 * action on that block — Save, approve, dismiss, opening it again — or with
 * the message it rides on.
 */

export const DRAFT_TTL_MS = 10 * 60 * 1000;

export interface NudgeDraft {
  date: string;
  eventId: string;
  name: string;
  /** "HH:MM" as drafted on the pad. */
  start: string;
  end: string;
}

interface Held extends NudgeDraft {
  expiresAt: number;
}

const held = new Map<number, Held>();

export function noteNudgeDraft(chatId: number, d: NudgeDraft, now: number = Date.now()): void {
  held.set(chatId, { ...d, expiresAt: now + DRAFT_TTL_MS });
}

/** Take the draft for this chat, if still live. Consumes it. */
export function takeNudgeDraft(chatId: number, now: number = Date.now()): NudgeDraft | undefined {
  const entry = held.get(chatId);
  if (!entry) return undefined;
  held.delete(chatId);
  if (entry.expiresAt <= now) return undefined;
  const { expiresAt: _expires, ...draft } = entry;
  return draft;
}

/** Drop the draft — only when it is for `eventId`, if one is given. */
export function clearNudgeDraft(chatId: number, eventId?: string): void {
  const entry = held.get(chatId);
  if (entry && (eventId === undefined || entry.eventId === eventId)) held.delete(chatId);
}

/** Test seam. Never called in production. */
export function resetNudgeDrafts(): void {
  held.clear();
}

/** The draft as the agent reads it. */
export function draftContext(d: NudgeDraft): string {
  return `Unsaved time edit on block "${d.name}" (id ${d.eventId}, ${d.date}): ${d.start}–${d.end}. `
    + "Apply these times together with whatever this message changes, in one update_event.";
}
