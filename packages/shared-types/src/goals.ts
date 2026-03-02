export interface Goal {
  name: string;
  status: string;
  priority: number;
  progress: number;
  target_date?: string;
}

export interface GoalsResponse {
  goals: Goal[];
}
