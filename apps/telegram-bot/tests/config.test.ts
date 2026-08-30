import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

describe("config", () => {
  const originalToken = process.env.TELEGRAM_BOT_TOKEN;
  const originalUserId = process.env.AUTHORIZED_USER_ID;
  const originalTimezone = process.env.VAULT_TIMEZONE;

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
});
