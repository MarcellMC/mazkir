/** Goal priority is stored in the vault as "high" | "medium" | "low", but
 * older payloads used the numeric 1-5 scale tasks use. Accept both. */
export type GoalPriority = number | string;

export interface Goal {
  name: string;
  status: string;
  priority: GoalPriority;
  progress: number;
  target_date?: string;
  /** Vault path, e.g. "30-goals/2026/get-fit.md" */
  path?: string;
  milestones?: string[];
}

/** Full goal detail from GET /goals/{slug} — frontmatter + note body. */
export interface GoalDetail extends Goal {
  /** Filename stem, e.g. "get-fit" — stable id for callbacks */
  slug: string;
  path: string;
  start_date?: string;
  category?: string;
  created?: string;
  updated?: string;
  /** Markdown body of the goal note (without frontmatter) */
  content: string;
}

export interface GoalsResponse {
  goals: Goal[];
}
