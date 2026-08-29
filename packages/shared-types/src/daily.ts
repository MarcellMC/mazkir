export interface DailyBlock {
  id: string;
  start: string;          // "HH:MM"
  end: string;            // "HH:MM"
  title: string;
  source: "calendar" | "timeline" | "merged" | "daily-note" | "habit";
  type: string;
  completed: boolean;
  activity: string | null;   // populated by Ship 6
  category: string | null;   // populated by Ship 6
  state: "suggested" | "approved";
  habit_progress: string | null;  // "1/2" when a daily_target is set
}

export interface DailyGap {
  start: string;
  end: string;
  minutes: number;
}

export interface DayCoverage {
  covered_minutes: number;
  unaccounted_minutes: number;
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
  /** Absent when talking to a vault-server from before Ship 1; the bot
   * falls back to an empty list rather than throwing. */
  todos?: DailyTodo[];
  notes: DailyNote[];
}
