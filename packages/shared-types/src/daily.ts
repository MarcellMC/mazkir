export interface DailyScheduleItem {
  start: string;           // ISO datetime or "HH:MM" for daily tasks / habits
  end?: string;            // ISO datetime; optional
  title: string;
  source: "calendar" | "daily-task" | "habit";
  completed: boolean;
  calendar_name?: string;  // present when source = "calendar"
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
  schedule: DailyScheduleItem[];
  todos: DailyTodo[];
  notes: DailyNote[];
}
