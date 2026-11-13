import type { Receipt } from "./receipt.js";

/** A message the server wants sent, riding back on a location point's response
 *  (location trips spec §6.1). Acknowledge it once sent, or it comes again. */
export interface LocationNotify {
  id: string;
  kind: "question" | "arrival" | "notice";
  receipt: Receipt;
}

/** `POST /locations/points`. `notify` is present only with LOCATION_AWARENESS=on. */
export interface LocationIngestResponse {
  ok: boolean;
  notify?: LocationNotify[];
}

/** `POST /locations/trips/{id}/tap`: the redrawn message, a toast, and a question to hold. */
export interface TripTapResult {
  receipt: Receipt | null;
  toast: string | null;
  open_question: string | null;
}
