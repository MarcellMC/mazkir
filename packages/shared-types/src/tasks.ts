export interface Task {
  name: string;
  status: string;
  priority: number;
  due_date?: string;
  category?: string;
  google_event_id?: string | null;
  /** Vault path, e.g. "40-tasks/active/buy-groceries.md" */
  path?: string;
}

/** Full task detail from GET /tasks/{slug} — frontmatter + note body. */
export interface TaskDetail extends Task {
  /** Filename stem, e.g. "buy-groceries" — stable id for callbacks */
  slug: string;
  path: string;
  tokens_on_completion?: number;
  created?: string;
  updated?: string;
  /** Markdown body of the task note (without frontmatter) */
  content: string;
}

export interface TasksResponse {
  tasks: Task[];
}
