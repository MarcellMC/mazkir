export interface Goal {
  name: string;
  status: string;
  priority: number;
  progress: number;
  target_date?: string;
  milestones?: string[];
  /** Vault path, e.g. "30-goals/2026/learn-spanish.md" */
  path?: string;
}

/** Full goal detail from GET /goals/{slug} — frontmatter + note body. */
export interface GoalDetail {
  name: string;
  /** Filename stem, e.g. "learn-spanish" — stable id for callbacks */
  slug: string;
  status: string;
  /** Numeric (1-5) or label ("medium") depending on vault frontmatter */
  priority: number | string;
  progress: number;
  target_date?: string;
  category?: string;
  milestones?: string[];
  created?: string;
  updated?: string;
  path: string;
  /** Markdown body of the goal note (without frontmatter) */
  content: string;
}

export interface GoalsResponse {
  goals: Goal[];
}
