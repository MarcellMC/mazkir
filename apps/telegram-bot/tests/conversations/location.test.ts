import { describe, it, expect, vi, beforeEach } from "vitest";
import { Api, Context } from "grammy";
import type { Update, UserFromGetMe } from "grammy/types";

const cfg = vi.hoisted(() => ({ locationIngest: true, authorizedUserId: 123 }));
vi.mock("../../src/config.js", () => ({ config: cfg }));

const api = vi.hoisted(() => ({ postLocationPoint: vi.fn() }));
vi.mock("../../src/api/client.js", () => {
  class ApiError extends Error {
    constructor(readonly status: number, statusText: string) {
      super(`API error: ${status} ${statusText}`);
    }
  }
  return { api, ApiError };
});

const log = vi.hoisted(() => ({ warn: vi.fn(), info: vi.fn(), error: vi.fn() }));
vi.mock("../../src/logger.js", () => ({ logger: log }));

import { locationHandler, toLocationPoint } from "../../src/conversations/location.js";
import { ApiError } from "../../src/api/client.js";

const me = { id: 1, is_bot: true, first_name: "Mazkir", username: "mazkir_bot" } as UserFromGetMe;
const chat = { id: 123, type: "private", first_name: "M" } as const;
const from = { id: 123, is_bot: false, first_name: "M" };
const LOC = { latitude: 32.0853, longitude: 34.7818, horizontal_accuracy: 12 };

async function fire(update: Omit<Update, "update_id">) {
  const ctx = new Context({ update_id: 1, ...update } as Update, new Api("test-token"), me);
  const next = vi.fn(async () => {});
  await locationHandler.middleware()(ctx, next);
  return next;
}

const edit = (location: object) => ({
  edited_message: { message_id: 7, date: 1762409000, edit_date: 1762409643, chat, from, location },
});
const msg = (extra: object) => ({ message: { message_id: 9, date: 1762409000, chat, from, ...extra } });

describe("location ingest", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    cfg.locationIngest = true;
    api.postLocationPoint.mockResolvedValue({ ok: true });
  });

  it("an edited live location posts one point stamped with edit_date and never reaches next", async () => {
    const next = await fire(edit({ ...LOC, heading: 270, live_period: 28800 }));
    expect(api.postLocationPoint).toHaveBeenCalledOnce();
    expect(api.postLocationPoint).toHaveBeenCalledWith({
      source: "telegram",
      kind: "live",
      message_id: 7,
      ts: new Date(1762409643 * 1000).toISOString(),
      lat: 32.0853,
      lng: 34.7818,
      accuracy_m: 12,
      heading: 270,
      live_period: 28800,
    });
    expect(next).not.toHaveBeenCalled();
  });

  it("a live share starting posts live_start and does not reach the agent", async () => {
    const next = await fire(msg({ location: { ...LOC, live_period: 900 } }));
    expect(api.postLocationPoint).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "live_start", message_id: 9, live_period: 900,
        ts: new Date(1762409000 * 1000).toISOString() }),
    );
    expect(next).not.toHaveBeenCalled();
  });

  it("a one-off location posts a check_in and still reaches the agent", async () => {
    const next = await fire(msg({ location: { latitude: 32.0853, longitude: 34.7818 } }));
    expect(api.postLocationPoint).toHaveBeenCalledWith({
      source: "telegram",
      kind: "check_in",
      message_id: 9,
      ts: new Date(1762409000 * 1000).toISOString(),
      lat: 32.0853,
      lng: 34.7818,
    });
    expect(next).toHaveBeenCalledOnce();
  });

  it("a venue is a check_in carrying its title", async () => {
    const venueLoc = { latitude: 32.07, longitude: 34.79 };
    const next = await fire(msg({ location: venueLoc, venue: { location: venueLoc, title: "Superpharm", address: "x" } }));
    expect(api.postLocationPoint).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "check_in", venue_title: "Superpharm", lat: 32.07 }),
    );
    expect(next).toHaveBeenCalledOnce();
  });

  it("a check-in whose post fails still reaches the agent and logs no coordinates", async () => {
    api.postLocationPoint.mockRejectedValue(new ApiError(404, "Not Found"));
    const next = await fire(msg({ location: { latitude: 32.0853, longitude: 34.7818 } }));
    expect(next).toHaveBeenCalledOnce();
    expect(log.warn).toHaveBeenCalledOnce();
    const [logged] = log.warn.mock.calls[0]!;
    expect(logged).toMatchObject({ event_type: "location_ingest_failed", kind: "check_in", status: 404 });
    const text = JSON.stringify(logged);
    expect(text).not.toContain("32.08");
    expect(text).not.toContain("34.78");
  });

  it("a failed live post is logged and swallowed", async () => {
    api.postLocationPoint.mockRejectedValue(new Error("ECONNREFUSED"));
    await expect(fire(edit(LOC))).resolves.toBeDefined();
    expect(log.warn).toHaveBeenCalledWith(
      expect.objectContaining({ event_type: "location_ingest_failed", kind: "live", status: "error" }),
      "location_ingest_failed",
    );
  });

  it("with ingest off nothing is posted and every location reaches next", async () => {
    cfg.locationIngest = false;
    expect(await fire(msg({ location: { ...LOC, live_period: 900 } }))).toHaveBeenCalledOnce();
    expect(await fire(msg({ location: LOC }))).toHaveBeenCalledOnce();
    expect(await fire(edit(LOC))).toHaveBeenCalledOnce();
    expect(api.postLocationPoint).not.toHaveBeenCalled();
  });

  it("text messages pass straight through", async () => {
    const next = await fire(msg({ text: "hello" }));
    expect(next).toHaveBeenCalledOnce();
    expect(api.postLocationPoint).not.toHaveBeenCalled();
  });
});

describe("toLocationPoint", () => {
  it("falls back to the message date when an edit has no edit_date", () => {
    const p = toLocationPoint({ message_id: 7, date: 1762409000, chat, location: LOC } as any, "live");
    expect(p.ts).toBe(new Date(1762409000 * 1000).toISOString());
  });
});
