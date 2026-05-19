import { describe, it, expect, beforeEach, afterEach } from "vitest";

describe("tracing init", () => {
  const original = process.env.OTEL_EXPORTER_OTLP_ENDPOINT;

  beforeEach(() => {
    delete process.env.OTEL_EXPORTER_OTLP_ENDPOINT;
  });

  afterEach(() => {
    if (original !== undefined) process.env.OTEL_EXPORTER_OTLP_ENDPOINT = original;
    else delete process.env.OTEL_EXPORTER_OTLP_ENDPOINT;
  });

  it("loads without throwing when endpoint is unset", async () => {
    await expect(import("../src/tracing.js")).resolves.toBeDefined();
  });
});
