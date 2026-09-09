/**
 * Which day the user is looking at, and whether that is still true.
 *
 * The hint only counts while the day view is the last thing the bot sent
 * to the chat. Send anything else — an agent reply, /tasks, a photo
 * acknowledgement — and it is dropped: a day view that has scrolled off
 * behind other output is no longer what the user is looking at, and a date
 * they have forgotten selecting must not silently steer a much later
 * message.
 *
 * No clock and no tuning parameter, deliberately. A TTL would be wrong in
 * both directions: too short mid-conversation, too long after walking away.
 *
 * In-memory, like pending-confirmations.ts: this is a property of the
 * current conversation, and falling back to today after a restart is the
 * safe default.
 */
interface Entry {
  date: string;
  /** True while the day view is still the bot's most recent message here. */
  onScreen: boolean;
}

const state = new Map<number, Entry>();

export function setSelectedDate(chatId: number, date: string): void {
  state.set(chatId, { date, onScreen: false });
}

export function noteDayView(chatId: number): void {
  const entry = state.get(chatId);
  if (entry) entry.onScreen = true;
}

export function noteOtherSend(chatId: number): void {
  const entry = state.get(chatId);
  if (entry) entry.onScreen = false;
}

export function getSelectedDate(chatId: number): string | undefined {
  const entry = state.get(chatId);
  return entry?.onScreen ? entry.date : undefined;
}

/** Test seam. Never called in production. */
export function resetSelectedDates(): void {
  state.clear();
}
