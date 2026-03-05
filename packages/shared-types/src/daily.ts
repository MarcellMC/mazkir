export interface HabitStatus {
  name: string;
  completed: boolean;
  streak: number;
}

export interface CalendarEvent {
  id: string;
  summary: string;
  start: string;
  end: string;
  completed: boolean;
  calendar: string;
}

export interface DailyResponse {
  date: string;
  day_of_week: string;
  tokens_earned: number;
  tokens_total: number;
  habits: HabitStatus[];
  calendar_events: CalendarEvent[];
  notes: string[];
}
