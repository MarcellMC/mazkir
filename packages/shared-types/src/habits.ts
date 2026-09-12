export interface Habit {
  name: string;
  frequency: string;
  streak: number;
  last_completed?: string;
  tokens_per_completion: number;
  completed_today: boolean;
}

export interface HabitsResponse {
  habits: Habit[];
}

/** What `PATCH /habits/{name}` returns. `already_completed` discriminates the
 *  two shapes: on a repeat tap the award fields are absent, because nothing was
 *  written and no tokens were paid. Typing this at all is the point — the bot
 *  used to declare the response `unknown` and throw it away, so a completion
 *  that awarded nothing was reported exactly like one that awarded five. */
export interface HabitCompletion {
  already_completed: boolean;
  name: string;
  completions_today: number;
  daily_target: number;
  streak?: number;
  old_streak?: number;
  new_streak?: number;
  tokens_earned?: number;
  new_token_total?: number | null;
  target_met?: boolean;
}
