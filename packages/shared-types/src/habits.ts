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
