import type { Task } from "@mazkir/shared-types";
import { callbackSlug } from "./slug.js";

/** Stable short id for a task — the vault filename stem.
 *
 *  The list and detail keyboards that used to live here are gone: task
 *  buttons are in-view navigation, so they now render in the message body
 *  as `<tg-button-row>` elements (see formatters/tasks-rich.ts). A view's
 *  `reply_markup` carries only the cross-view keyboard (keyboards/nav.ts). */
export function taskSlug(task: Task): string {
  return callbackSlug(task);
}
