import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

describe("config", () => {
  const originalToken = process.env.TELEGRAM_BOT_TOKEN;
  const originalUserId = process.env.AUTHORIZED_USER_ID;
  const originalTimezone = process.env.VAULT_TIMEZONE;
  const originalStream = process.env.STREAM_RESPONSES;

  beforeEach(() => {
    vi.resetModules();
    // loadConfig() throws without these two, so pin them for every case in
    // this file — this suite is about vaultTimezone, not the required
    // fields.
    process.env.TELEGRAM_BOT_TOKEN = "test-token";
    process.env.AUTHORIZED_USER_ID = "123";
  });

  afterEach(() => {
    const restore = (key: string, value: string | undefined) => {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    };
    restore("TELEGRAM_BOT_TOKEN", originalToken);
    restore("AUTHORIZED_USER_ID", originalUserId);
    restore("VAULT_TIMEZONE", originalTimezone);
    restore("STREAM_RESPONSES", originalStream);
  });

  it("falls back to Asia/Jerusalem when VAULT_TIMEZONE is unset", async () => {
    // Must agree with the server's VAULT_TIMEZONE default
    // (apps/vault-server/src/config.py) — day-rich.ts's "today" label
    // depends on the two staying in sync.
    delete process.env.VAULT_TIMEZONE;
    const { config } = await import("../src/config.js");
    expect(config.vaultTimezone).toBe("Asia/Jerusalem");
  });

  it("reads VAULT_TIMEZONE from the environment when set", async () => {
    process.env.VAULT_TIMEZONE = "America/New_York";
    const { config } = await import("../src/config.js");
    expect(config.vaultTimezone).toBe("America/New_York");
  });

  it("streams by default when STREAM_RESPONSES is unset", async () => {
    // A fast-lane receipt is sent as soon as it exists only on the streaming
    // path; a non-streaming reply waits for the Google syncs first.
    delete process.env.STREAM_RESPONSES;
    const { config } = await import("../src/config.js");
    expect(config.streamResponses).toBe(true);
  });

  it("turns streaming off only for an explicit STREAM_RESPONSES=false", async () => {
    process.env.STREAM_RESPONSES = "false";
    const { config } = await import("../src/config.js");
    expect(config.streamResponses).toBe(false);
  });
});
