/** Google Calendar event as returned by GET /calendar/events. */
export interface CalendarEvent {
  id: string;
  summary: string;
  /** ISO datetime, or date-only string for all-day events */
  start: string;
  end: string;
  completed: boolean;
  /** Source calendar name, e.g. "Mazkir" */
  calendar: string;
}
