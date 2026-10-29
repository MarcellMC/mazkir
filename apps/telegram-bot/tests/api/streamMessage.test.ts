import { describe, it, expect, vi } from "vitest";

// Mock config before importing client
vi.mock("../../src/config.js", () => ({
  config: {
    vaultServerUrl: "http://localhost:8000",
    vaultServerApiKey: "test-key",
    streamResponses: false,
  },
}));

const { streamMessage } = await import("../../src/api/client.js");

function makeSseResponse(events: string[]): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const e of events) {
        controller.enqueue(encoder.encode(`data: ${e}\n\n`));
      }
      controller.close();
    },
  });
  return new Response(body, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

describe("streamMessage", () => {
  it("forwards text chunks and resolves with final payload", async () => {
    const chunks: string[] = [];
    const mockFetch = vi.fn().mockResolvedValue(
      makeSseResponse([
        JSON.stringify({ text: "Hello" }),
        JSON.stringify({ text: " world" }),
        JSON.stringify({
          done: true,
          response: { response: "Hello world", iterations: 1 },
        }),
      ]),
    );
    vi.stubGlobal("fetch", mockFetch);

    try {
      const result = await streamMessage(
        { text: "hi", chat_id: 1 },
        (c) => chunks.push(c),
        "http://localhost:8000",
        "test-key",
      );
      expect(chunks).toEqual(["Hello", " world"]);
      expect(result.response).toBe("Hello world");
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("sends ?stream=true query param and X-API-Key header", async () => {
    const mockFetch = vi.fn().mockResolvedValue(
      makeSseResponse([
        JSON.stringify({ done: true, response: { response: "ok", iterations: 1 } }),
      ]),
    );
    vi.stubGlobal("fetch", mockFetch);

    try {
      await streamMessage({ text: "ping", chat_id: 2 }, () => {}, "http://test:9000", "my-key");
      expect(mockFetch).toHaveBeenCalledWith(
        "http://test:9000/message?stream=true",
        expect.objectContaining({
          method: "POST",
          headers: expect.objectContaining({
            "X-API-Key": "my-key",
            Accept: "text/event-stream",
          }),
        }),
      );
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("throws when stream ends without final payload", async () => {
    const mockFetch = vi.fn().mockResolvedValue(
      makeSseResponse([JSON.stringify({ text: "partial..." })]),
    );
    vi.stubGlobal("fetch", mockFetch);

    try {
      await expect(
        streamMessage({ text: "hi", chat_id: 3 }, () => {}),
      ).rejects.toThrow("SSE stream ended without final payload");
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("throws on non-2xx HTTP response", async () => {
    const mockFetch = vi.fn().mockResolvedValue(
      new Response("Internal Server Error", { status: 500 }),
    );
    vi.stubGlobal("fetch", mockFetch);

    try {
      await expect(
        streamMessage({ text: "hi", chat_id: 4 }, () => {}),
      ).rejects.toThrow("SSE stream failed: 500");
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("hands stages, the receipt and its updates to their handlers, as they arrive", async () => {
    const receipt = { turn_id: "t0000beef", lines: [], undo: null, open_question: null, text: "✓ Gym" };
    const mockFetch = vi.fn().mockResolvedValue(
      makeSseResponse([
        JSON.stringify({ stage: "Reading…" }),
        JSON.stringify({ receipt }),
        JSON.stringify({ text: "and more" }),
        JSON.stringify({ receipt_update: { line_id: 0, receipt } }),
        JSON.stringify({ done: true, response: { response: "and more", route: "mixed", receipt } }),
      ]),
    );
    vi.stubGlobal("fetch", mockFetch);
    const seen: string[] = [];
    try {
      const final = await streamMessage(
        { text: "hi", chat_id: 1, message_id: 5 },
        {
          onChunk: (t) => { seen.push(`text:${t}`); },
          onStage: (s) => { seen.push(`stage:${s}`); },
          onReceipt: (r) => { seen.push(`receipt:${r.turn_id}`); },
          onReceiptUpdate: (u) => { seen.push(`update:${u.line_id}`); },
        },
        "http://localhost:8000",
        "test-key",
      );
      // An update may follow the text: the server awaits Google syncs after the agent.
      expect(seen).toEqual(["stage:Reading…", "receipt:t0000beef", "text:and more", "update:0"]);
      expect(final.route).toBe("mixed");
      expect(JSON.parse(mockFetch.mock.calls[0][1].body).message_id).toBe(5);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("a throwing handler does not lose later frames or the final response", async () => {
    const mockFetch = vi.fn().mockResolvedValue(
      makeSseResponse([
        JSON.stringify({ stage: "Reading…" }),
        JSON.stringify({ text: "hello" }),
        JSON.stringify({ done: true, response: { response: "hello", route: "fast" } }),
      ]),
    );
    vi.stubGlobal("fetch", mockFetch);
    const seen: string[] = [];
    try {
      const final = await streamMessage(
        { text: "hi", chat_id: 1 },
        {
          onChunk: (t) => { seen.push(t); },
          onStage: () => { throw new Error("edit failed"); },
        },
        "http://localhost:8000",
        "test-key",
      );
      expect(seen).toEqual(["hello"]);
      expect(final.response).toBe("hello");
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
