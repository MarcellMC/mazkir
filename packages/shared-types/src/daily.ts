export interface DailyBlock {
  id: string;
  start: string;          // "HH:MM"
  end: string;            // "HH:MM"
  title: string;
  /** `"manual"` and `"photo"` are what `create_event` and photo attachment
   *  write, and they are the blocks the user authored directly — the ones
   *  `resolve_state` auto-approves. They were missing from this union while
   *  the server had been emitting them since Ship 4, so no bot code could
   *  branch on "did I make this myself" without TypeScript rejecting the
   *  comparison as impossible. */
  source:
    | "calendar"
    | "timeline"
    | "merged"
    | "daily-note"
    | "habit"
    | "manual"
    | "photo";
  type: string;
  completed: boolean;
  activity: string | null;   // populated by Ship 6
  category: string | null;   // populated by Ship 6
  /** Resolved server-side (spec §2.1): derived from the source for anything
   *  a human action created, stored only for calendar and timeline blocks the
   *  user has tapped. `"dismissed"` never arrives here — the server omits
   *  those blocks — but the vocabulary mirrors the server's rather than
   *  inventing a narrower one that would drift from it. */
  state: "approved" | "pending" | "dismissed";
  habit_progress: string | null;  // "1/2" when a daily_target is set
}

/** What probably filled a gap. A question, not an assertion: the row renders
 *  it with a ✕ beside it, and `days_seen` is shown so the guess can be judged
 *  rather than trusted. */
export interface GapProposal {
  name: string;
  days_seen: number;
}

export interface DailyGap {
  start: string;
  end: string;
  minutes: number;
  /** null means Mazkir had no basis to guess, so the gap asks instead. */
  proposal: GapProposal | null;
}

/** A block with no drawable interval — missing a start or an end time.
 *  Kept out of `blocks` deliberately: it has no interval, contributes
 *  nothing to coverage, and the gap it sits inside is what prompts you to
 *  finish it. */
export interface DailyIncomplete {
  id: string;
  title: string;
  start?: string | null;
  end?: string | null;
  missing: string[];
  source: string;
}

export interface DayCoverage {
  /** Union over every drawable block — what gaps are computed from, so a `░`
   *  row always means nothing is there at all. Meaning unchanged from Ship 2,
   *  so existing consumers are unaffected. */
  covered_minutes: number;
  unaccounted_minutes: number;
  /** Minutes since local midnight for today, 1440 for a past day, 0 for a
   * future day. Carries the "is it today" signal for free: the bot needs no
   * timezone comparison at all — the divider between elapsed and
   * still-to-come rows shows exactly when `0 < elapsed_minutes < 1440`. */
  elapsed_minutes: number;
  /** Approved blocks only. The one number the weekly readout may read. */
  confirmed_minutes: number;
  /** Pending time not already confirmed, so two overlapping blocks of
   *  different states never add up to more than the wall clock. */
  pending_minutes: number;
}

export interface DailyNote {
  text?: string;
  photo_path?: string;
  caption?: string;
}

export interface DailyTodo {
  text: string;
  done: boolean;
  section: string;
  scheduled_at: string | null;
  duration_minutes: number | null;
}

export interface DailyResponse {
  date: string;
  tokens_today: number;
  tokens_total: number;
  blocks: DailyBlock[];
  gaps: DailyGap[];
  coverage: DayCoverage;
  /** Absent when talking to a vault-server from before this ship; the bot
   * falls back to an empty list rather than throwing. */
  incomplete?: DailyIncomplete[];
  /** Absent when talking to a vault-server from before Ship 1; the bot
   * falls back to an empty list rather than throwing. */
  todos?: DailyTodo[];
  notes: DailyNote[];
}
