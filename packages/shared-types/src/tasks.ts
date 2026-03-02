export interface Task {
  name: string;
  status: string;
  priority: number;
  due_date?: string;
  category?: string;
}

export interface TasksResponse {
  tasks: Task[];
}
