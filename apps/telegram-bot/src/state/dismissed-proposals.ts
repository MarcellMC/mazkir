/**
 * Gap proposals the user has waved away, so ✕ visibly does something.
 *
 * `prop:dismiss` writes nothing to the vault — that was the deliberate
 * choice (spec §4.3: no tombstones, a refused proposal may ask again). But
 * the handler then re-renders the day, which recomputes the same proposal
 * and draws it straight back, so the tap looked broken: the toast said
 * "Skipped" while the row stayed exactly where it was. Observed in real use
 * on 2026-09-12.
 *
 * This closes the gap between the two without inventing a stored record.
 * The suppression lives here, in memory, and is consulted only by the
 * callback paths that re-render a day view already on screen. A fresh
 * `/day` does not consult it, and neither does a restart — which is the
 * agreed behaviour: gone now, free to ask again later.
 *
 * Keyed by chat + date + interval rather than by proposal name: the same
 * name may be proposed for two different holes in one day, and dismissing
 * one of them says nothing about the other.
 *
 * A TTL, unlike in selected-date.ts, is right here: "later" has to mean
 * something, and a suppression that outlived the sitting would silently
 * hide a proposal the user would now want. Thirty minutes is long enough to
 * keep adjusting the same day without the row flickering back.
 */

/** How long a dismissal holds. */
export const SUPPRESS_MS = 30 * 60 * 1000;

/** Key → expiry timestamp. */
const suppressed = new Map<string, number>();

function key(chatId: number, date: string, start: string, end: string): string {
  return `${chatId}:${date}:${start}-${end}`;
}

/** Drop expired entries. Called on every read and write, so the map cannot
 *  grow without bound in a long-running process — there is no other reaper. */
function sweep(now: number): void {
  for (const [k, expiry] of suppressed) {
    if (expiry <= now) suppressed.delete(k);
  }
}

export function suppressProposal(
  chatId: number,
  date: string,
  start: string,
  end: string,
  now: number = Date.now(),
): void {
  sweep(now);
  suppressed.set(key(chatId, date, start, end), now + SUPPRESS_MS);
}

export function isProposalSuppressed(
  chatId: number,
  date: string,
  start: string,
  end: string,
  now: number = Date.now(),
): boolean {
  sweep(now);
  const expiry = suppressed.get(key(chatId, date, start, end));
  return expiry !== undefined && expiry > now;
}

/** Test seam. Never called in production. */
export function resetDismissedProposals(): void {
  suppressed.clear();
}

/** A day payload with the user's dismissed proposals removed.
 *
 * The gap itself stays — that time genuinely is unaccounted, and hiding the
 * row would misreport the day. Only the suggestion goes, so the row falls
 * back to the plain `+ Xh` fill button.
 *
 * Returns a shallow copy with a new `gaps` array; the input is left alone so
 * a caller can still report on what the server actually said.
 */
export function stripSuppressedProposals<
  T extends { date: string; gaps: { start: string; end: string; proposal: unknown }[] },
>(chatId: number, data: T): T {
  return {
    ...data,
    gaps: data.gaps.map((g) =>
      g.proposal && isProposalSuppressed(chatId, data.date, g.start, g.end)
        ? { ...g, proposal: null }
        : g,
    ),
  };
}
