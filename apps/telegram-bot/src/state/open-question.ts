/**
 * The last question the bot asked on its own initiative, so an answer to it
 * is understood as one.
 *
 * When you tap `+ 2.5h` on a gap, the bot replies "15:00–17:30 on 2026-09-12
 * is unaccounted — what was it?". That reply is sent by the bot directly; it
 * never goes through `POST /message`, so the server has no record of it. If
 * you then use Telegram's reply-to, `reply_to` carries the question and the
 * agent has the interval. If you just type "Bar hopping" — which is the
 * natural thing to do, and what happened on 2026-09-12 at 17:56 — the agent
 * receives two words with no times and has to ask again for the very interval
 * the bot named one message earlier.
 *
 * So the bot remembers its own question and, when the next message carries no
 * real reply-to, presents it as the `reply_to` the user did not have to make.
 * That reuses the path the server already handles (`[Replying to assistant:
 * "…"]` in the prompt) rather than adding a second, parallel notion of
 * pending context. It is not a fabrication: the bot did ask this, one turn
 * ago, and the user is answering it.
 *
 * One-shot and short-lived, because both failure modes are real: a question
 * that outlives its answer would attach a stale interval to an unrelated
 * message, which is worse than asking again.
 *
 * In-memory, like selected-date.ts and dismissed-proposals.ts — a question
 * the bot forgot across a restart is simply one the user answers again.
 */

/** How long an unanswered question stays attachable. */
export const QUESTION_TTL_MS = 10 * 60 * 1000;

interface Pending {
  /** Exactly what the bot asked, as the user saw it. */
  text: string;
  expiresAt: number;
}

const pending = new Map<number, Pending>();

/** Record a question the bot asked unprompted. */
export function noteOpenQuestion(
  chatId: number,
  text: string,
  now: number = Date.now(),
): void {
  pending.set(chatId, { text, expiresAt: now + QUESTION_TTL_MS });
}

/**
 * Take the open question for this chat, if it is still live. Consumes it:
 * a question is answered once, and leaving it attachable would let it ride
 * along on later, unrelated messages.
 */
export function takeOpenQuestion(
  chatId: number,
  now: number = Date.now(),
): string | undefined {
  const entry = pending.get(chatId);
  if (!entry) return undefined;
  pending.delete(chatId);
  return entry.expiresAt > now ? entry.text : undefined;
}

/** Drop a chat's open question without using it — the user moved on. */
export function clearOpenQuestion(chatId: number): void {
  pending.delete(chatId);
}

/** Test seam. Never called in production. */
export function resetOpenQuestions(): void {
  pending.clear();
}
