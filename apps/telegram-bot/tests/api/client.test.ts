import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock config before importing client
vi.mock("../../src/config.js", () => ({
  config: {
    vaultServerUrl: "http://localhost:8000",
    vaultServerApiKey: "test-key",
  },
}));

const { createApiClient } = await import("../../src/api/client.js");

describe("ApiClient", () => {
  let api: ReturnType<typeof createApiClient>;

  beforeEach(() => {
    api = createApiClient("http://localhost:8000", "test-key");
    vi.restoreAllMocks();
  });

  it("getDaily fetches /daily", async () => {
    const mockResponse = {
      date: "2026-03-02",
      day_of_week: "Monday",
      tokens_earned: 10,
      tokens_total: 100,
      habits: [],
      calendar_events: [],
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(mockResponse), { status: 200 })
    );

    const result = await api.getDaily();
    expect(result).toEqual(mockResponse);
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/daily",
      expect.objectContaining({
        headers: expect.objectContaining({
          "X-API-Key": "test-key",
        }),
      })
    );
  });

  it("completeTask sends PATCH with completed: true", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ success: true }), { status: 200 })
    );

    await api.completeTask("buy-milk");
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/tasks/buy-milk",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ completed: true }),
      })
    );
  });

  it("sendMessage sends enriched payload with attachments", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({ intent: "GENERAL_CHAT", response: "Got the photo!" }),
        { status: 200 },
      ),
    );

    await api.sendMessage({
      text: "Dog walk",
      chat_id: 123,
      attachments: [
        { type: "location", latitude: 32.08, longitude: 34.78 },
      ],
      reply_to: { text: "previous msg", from: "assistant" as const },
    });

    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/message",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          text: "Dog walk",
          chat_id: 123,
          attachments: [
            { type: "location", latitude: 32.08, longitude: 34.78 },
          ],
          reply_to: { text: "previous msg", from: "assistant" },
        }),
      }),
    );
  });

  it("throws on non-2xx response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("Not found", { status: 404 })
    );

    await expect(api.getDaily()).rejects.toThrow("404");
  });
});
