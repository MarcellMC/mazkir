# Rich Messages Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable the Telegram bot to handle photo attachments, location messages, reply/quote context, and forwarded messages — passing them through the agent loop so Claude can decide what to do.

**Architecture:** Extend the existing `MessageRequest` payload with optional `attachments`, `reply_to`, and `forwarded_from` fields. The bot extracts these from Telegram messages, downloads and base64-encodes photos, and sends everything in one POST. The server saves photos to `data/media/`, builds multi-content Claude messages (image blocks + text), and lets the agent loop decide actions via a new `attach_to_daily` tool.

**Tech Stack:** TypeScript (grammY bot), Python (FastAPI server), Anthropic Claude API (vision), shared-types package

**Design doc:** `docs/plans/2026-03-04-rich-messages-design.md`

---

### Task 1: Extend Shared Types

**Files:**
- Modify: `packages/shared-types/src/message.ts`

**Step 1: Add the new interfaces and extend MessageRequest**

Add `Attachment`, `ReplyContext`, `ForwardContext` interfaces and extend `MessageRequest`:

```typescript
// After the existing Intent type (line 8), before MessageRequest (line 10):

export interface Attachment {
  type: "photo" | "location";
  /** base64-encoded image bytes (photo only) */
  data?: string;
  /** MIME type, e.g. "image/jpeg" (photo only) */
  mime_type?: string;
  /** e.g. "photo_2026-03-04_14-30.jpg" (photo only) */
  filename?: string;
  /** Location fields */
  latitude?: number;
  longitude?: number;
  /** Venue name if sent as venue */
  title?: string;
}

export interface ReplyContext {
  /** Text of the message being replied to */
  text: string;
  /** Whether the original was from user or assistant (bot) */
  from: "user" | "assistant";
}

export interface ForwardContext {
  /** Name of the original sender/channel */
  from_name: string;
  /** Text content of the forwarded message */
  text: string;
  /** Original message date ISO string */
  date?: string;
}
```

Then modify the existing `MessageRequest` (line 10-13) to add optional fields:

```typescript
export interface MessageRequest {
  text: string;
  chat_id: number;
  attachments?: Attachment[];
  reply_to?: ReplyContext;
  forwarded_from?: ForwardContext;
}
```

**Step 2: Build shared-types**

Run: `cd ~/dev/mazkir/packages/shared-types && npx tsc -b`
Expected: Clean build, no errors

**Step 3: Commit**

```bash
git add packages/shared-types/src/message.ts
git commit -m "feat(shared-types): add Attachment, ReplyContext, ForwardContext interfaces"
```

---

### Task 2: Expand Bot Message Handler

**Files:**
- Modify: `apps/telegram-bot/src/conversations/message.ts`

**Context:**
- Current handler only listens to `message:text` (line 9)
- grammY `ctx.message.photo` is an array of `PhotoSize` objects — use the last (largest) one
- `bot.api.getFile(file_id)` returns `{ file_path: string }`, download via `https://api.telegram.org/file/bot<TOKEN>/<file_path>`
- `ctx.message.reply_to_message` contains the quoted message
- `ctx.message.forward_origin` contains forward info (grammY v1 uses this)
- Need to import `bot` for `bot.api.getFile()` and config for token URL construction

**Step 1: Write the failing test**

Create: `apps/telegram-bot/tests/conversations/message.test.ts`

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("../../src/config.js", () => ({
  config: {
    botToken: "test-token",
    vaultServerUrl: "http://localhost:8000",
    vaultServerApiKey: "test-key",
    authorizedUserId: 123,
    webappUrl: "http://localhost:5173",
    logLevel: "INFO",
  },
}));

vi.mock("../../src/api/client.js", () => ({
  api: {
    sendMessage: vi.fn(),
    sendConfirmation: vi.fn(),
  },
}));

// Test the extraction helpers (exported for testing)
const { buildMessagePayload } = await import(
  "../../src/conversations/message.js"
);

describe("buildMessagePayload", () => {
  it("builds payload from plain text message", () => {
    const msg = {
      text: "hello",
      caption: undefined,
      photo: undefined,
      location: undefined,
      venue: undefined,
      reply_to_message: undefined,
      forward_origin: undefined,
    } as any;

    const payload = buildMessagePayload(msg, 123);
    expect(payload.text).toBe("hello");
    expect(payload.chat_id).toBe(123);
    expect(payload.attachments).toBeUndefined();
    expect(payload.reply_to).toBeUndefined();
  });

  it("extracts location attachment", () => {
    const msg = {
      text: undefined,
      caption: undefined,
      photo: undefined,
      location: { latitude: 32.08, longitude: 34.78 },
      venue: undefined,
      reply_to_message: undefined,
      forward_origin: undefined,
    } as any;

    const payload = buildMessagePayload(msg, 123);
    expect(payload.attachments).toHaveLength(1);
    expect(payload.attachments![0]).toEqual({
      type: "location",
      latitude: 32.08,
      longitude: 34.78,
    });
  });

  it("extracts venue attachment with title", () => {
    const msg = {
      text: undefined,
      caption: undefined,
      photo: undefined,
      location: undefined,
      venue: {
        location: { latitude: 32.08, longitude: 34.78 },
        title: "Coffee Shop",
      },
      reply_to_message: undefined,
      forward_origin: undefined,
    } as any;

    const payload = buildMessagePayload(msg, 123);
    expect(payload.attachments).toHaveLength(1);
    expect(payload.attachments![0]).toEqual({
      type: "location",
      latitude: 32.08,
      longitude: 34.78,
      title: "Coffee Shop",
    });
  });

  it("extracts reply context from bot message", () => {
    const msg = {
      text: "yes do it",
      caption: undefined,
      photo: undefined,
      location: undefined,
      venue: undefined,
      reply_to_message: {
        text: "Should I create this task?",
        from: { is_bot: true },
      },
      forward_origin: undefined,
    } as any;

    const payload = buildMessagePayload(msg, 123);
    expect(payload.reply_to).toEqual({
      text: "Should I create this task?",
      from: "assistant",
    });
  });

  it("extracts reply context from user message", () => {
    const msg = {
      text: "what about this?",
      caption: undefined,
      photo: undefined,
      location: undefined,
      venue: undefined,
      reply_to_message: {
        text: "I went for a run",
        from: { is_bot: false },
      },
      forward_origin: undefined,
    } as any;

    const payload = buildMessagePayload(msg, 123);
    expect(payload.reply_to).toEqual({
      text: "I went for a run",
      from: "user",
    });
  });

  it("extracts forward context from user forward", () => {
    const msg = {
      text: "Check this out",
      caption: undefined,
      photo: undefined,
      location: undefined,
      venue: undefined,
      reply_to_message: undefined,
      forward_origin: {
        type: "user",
        sender_user: { first_name: "Alice" },
        date: 1709568000,
      },
    } as any;

    const payload = buildMessagePayload(msg, 123);
    expect(payload.forwarded_from).toEqual({
      from_name: "Alice",
      text: "Check this out",
      date: expect.any(String),
    });
  });

  it("uses caption when text is absent (photo message)", () => {
    const msg = {
      text: undefined,
      caption: "Dog walk photo",
      photo: [
        { file_id: "small", width: 90, height: 90, file_size: 1000 },
        { file_id: "large", width: 800, height: 600, file_size: 50000 },
      ],
      location: undefined,
      venue: undefined,
      reply_to_message: undefined,
      forward_origin: undefined,
    } as any;

    const payload = buildMessagePayload(msg, 123);
    expect(payload.text).toBe("Dog walk photo");
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd ~/dev/mazkir/apps/telegram-bot && npx vitest run tests/conversations/message.test.ts`
Expected: FAIL — `buildMessagePayload` is not exported

**Step 3: Implement the extraction logic and update the handler**

Rewrite `apps/telegram-bot/src/conversations/message.ts`:

```typescript
import { Composer } from "grammy";
import type { Message } from "grammy/types";
import type { Attachment, ReplyContext, ForwardContext } from "@mazkir/shared-types";
import { api } from "../api/client.js";
import { config } from "../config.js";

// Pending confirmations: chatId -> actionId
const pendingConfirmations = new Map<number, string>();

/**
 * Build the enriched message payload from a Telegram message.
 * Exported for testing.
 */
export function buildMessagePayload(msg: Message, chatId: number) {
  // Text: prefer .text, fall back to .caption (for photo messages)
  const text = msg.text ?? msg.caption ?? "";

  // Attachments
  const attachments: Attachment[] = [];

  if (msg.location && !msg.venue) {
    attachments.push({
      type: "location",
      latitude: msg.location.latitude,
      longitude: msg.location.longitude,
    });
  }

  if (msg.venue) {
    attachments.push({
      type: "location",
      latitude: msg.venue.location.latitude,
      longitude: msg.venue.location.longitude,
      title: msg.venue.title,
    });
  }

  // Note: photo attachments handled separately (async download needed)
  // We just mark presence here; the handler adds the data after download.

  // Reply context
  let reply_to: ReplyContext | undefined;
  if (msg.reply_to_message?.text) {
    reply_to = {
      text: msg.reply_to_message.text,
      from: msg.reply_to_message.from?.is_bot ? "assistant" : "user",
    };
  }

  // Forward context
  let forwarded_from: ForwardContext | undefined;
  if (msg.forward_origin) {
    const origin = msg.forward_origin;
    let from_name = "Unknown";
    if (origin.type === "user" && "sender_user" in origin) {
      from_name = (origin as any).sender_user.first_name ?? "Unknown";
    } else if (origin.type === "channel" && "chat" in origin) {
      from_name = (origin as any).chat.title ?? "Channel";
    } else if (origin.type === "hidden_user" && "sender_user_name" in origin) {
      from_name = (origin as any).sender_user_name ?? "Hidden User";
    }
    forwarded_from = {
      from_name,
      text,
      date: new Date(origin.date * 1000).toISOString(),
    };
  }

  return {
    text,
    chat_id: chatId,
    ...(attachments.length > 0 ? { attachments } : {}),
    ...(reply_to ? { reply_to } : {}),
    ...(forwarded_from ? { forwarded_from } : {}),
  };
}

/**
 * Download a photo from Telegram and return base64-encoded bytes.
 */
async function downloadPhoto(
  fileId: string,
  botToken: string,
): Promise<{ data: string; mime_type: string } | null> {
  try {
    const fileRes = await fetch(
      `https://api.telegram.org/bot${botToken}/getFile?file_id=${fileId}`,
    );
    const fileJson = (await fileRes.json()) as {
      ok: boolean;
      result?: { file_path: string };
    };
    if (!fileJson.ok || !fileJson.result?.file_path) return null;

    const fileUrl = `https://api.telegram.org/file/bot${botToken}/${fileJson.result.file_path}`;
    const response = await fetch(fileUrl);
    if (!response.ok) return null;

    const buffer = await response.arrayBuffer();
    const base64 = Buffer.from(buffer).toString("base64");

    // Determine MIME type from file extension
    const ext = fileJson.result.file_path.split(".").pop()?.toLowerCase();
    const mime_type =
      ext === "png" ? "image/png" : ext === "webp" ? "image/webp" : "image/jpeg";

    return { data: base64, mime_type };
  } catch {
    return null;
  }
}

export const messageHandler = new Composer();

// Handle text, photo, and location messages
messageHandler.on(
  ["message:text", "message:photo", "message:location"],
  async (ctx) => {
    const msg = ctx.message;
    const chatId = ctx.chat.id;
    const text = msg.text ?? msg.caption ?? "";

    // Skip commands (already handled)
    if (text.startsWith("/")) return;

    try {
      await ctx.replyWithChatAction("typing");

      // Check for pending confirmation (only for plain text replies)
      const pendingActionId = pendingConfirmations.get(chatId);
      if (pendingActionId && msg.text && !msg.photo && !msg.location) {
        pendingConfirmations.delete(chatId);
        const response = await api.sendConfirmation(
          chatId,
          pendingActionId,
          text,
        );
        if (response.awaiting_confirmation && response.pending_action_id) {
          pendingConfirmations.set(chatId, response.pending_action_id);
        }
        await ctx.reply(response.response, { parse_mode: "HTML" });
        return;
      }

      // Build enriched payload
      const payload = buildMessagePayload(msg, chatId);

      // Download photo if present
      if (msg.photo && msg.photo.length > 0) {
        const largest = msg.photo[msg.photo.length - 1]!;
        const photoData = await downloadPhoto(largest.file_id, config.botToken);
        if (photoData) {
          const now = new Date();
          const filename = `photo_${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}_${String(now.getHours()).padStart(2, "0")}-${String(now.getMinutes()).padStart(2, "0")}-${String(now.getSeconds()).padStart(2, "0")}.jpg`;
          if (!payload.attachments) payload.attachments = [];
          payload.attachments.push({
            type: "photo",
            data: photoData.data,
            mime_type: photoData.mime_type,
            filename,
          });
        } else {
          // Photo download failed — append note to text
          payload.text = (payload.text ? payload.text + "\n" : "") +
            "[Photo attachment failed to download]";
        }
      }

      const response = await api.sendMessage(payload);

      if (response.awaiting_confirmation && response.pending_action_id) {
        pendingConfirmations.set(chatId, response.pending_action_id);
      }

      await ctx.reply(response.response, { parse_mode: "HTML" });
    } catch {
      await ctx.reply("❌ Something went wrong. Is vault-server running?");
    }
  },
);
```

**Step 4: Run test to verify it passes**

Run: `cd ~/dev/mazkir/apps/telegram-bot && npx vitest run tests/conversations/message.test.ts`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add apps/telegram-bot/src/conversations/message.ts apps/telegram-bot/tests/conversations/message.test.ts
git commit -m "feat(telegram-bot): extract attachments, reply context, forward context from messages"
```

---

### Task 3: Update Bot API Client

**Files:**
- Modify: `apps/telegram-bot/src/api/client.ts`
- Modify: `apps/telegram-bot/tests/api/client.test.ts`

**Step 1: Write the failing test**

Add to `apps/telegram-bot/tests/api/client.test.ts`:

```typescript
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
```

**Step 2: Run test to verify it fails**

Run: `cd ~/dev/mazkir/apps/telegram-bot && npx vitest run tests/api/client.test.ts`
Expected: FAIL — `sendMessage` currently takes `(text, chatId)` not an object

**Step 3: Update sendMessage signature**

In `apps/telegram-bot/src/api/client.ts`, change the sendMessage method (lines 65-69):

```typescript
// From:
sendMessage: (text: string, chatId: number) =>
  request<MessageResponse>("/message", {
    method: "POST",
    body: JSON.stringify({ text, chat_id: chatId }),
  }),

// To:
sendMessage: (payload: {
  text: string;
  chat_id: number;
  attachments?: import("@mazkir/shared-types").Attachment[];
  reply_to?: import("@mazkir/shared-types").ReplyContext;
  forwarded_from?: import("@mazkir/shared-types").ForwardContext;
}) =>
  request<MessageResponse>("/message", {
    method: "POST",
    body: JSON.stringify(payload),
  }),
```

Also add the import at the top:

```typescript
import type {
  // ... existing imports ...
  Attachment,
  ReplyContext,
  ForwardContext,
} from "@mazkir/shared-types";
```

**Step 4: Run tests to verify they pass**

Run: `cd ~/dev/mazkir/apps/telegram-bot && npx vitest run`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add apps/telegram-bot/src/api/client.ts apps/telegram-bot/tests/api/client.test.ts
git commit -m "feat(telegram-bot): update sendMessage to accept enriched payload"
```

---

### Task 4: Expand Server-Side Pydantic Models

**Files:**
- Modify: `apps/vault-server/src/api/routes/message.py`

**Step 1: Write the failing test**

Create: `apps/vault-server/tests/test_message_models.py`

```python
"""Tests for enriched message request models."""

import pytest
from pydantic import ValidationError


def test_plain_text_request():
    from src.api.routes.message import MessageRequest
    req = MessageRequest(text="hello", chat_id=123)
    assert req.text == "hello"
    assert req.attachments is None
    assert req.reply_to is None
    assert req.forwarded_from is None


def test_photo_attachment():
    from src.api.routes.message import MessageRequest, AttachmentModel
    req = MessageRequest(
        text="Dog walk",
        chat_id=123,
        attachments=[
            AttachmentModel(
                type="photo",
                data="base64data",
                mime_type="image/jpeg",
                filename="photo_2026-03-04_14-30.jpg",
            )
        ],
    )
    assert len(req.attachments) == 1
    assert req.attachments[0].type == "photo"
    assert req.attachments[0].data == "base64data"


def test_location_attachment():
    from src.api.routes.message import MessageRequest, AttachmentModel
    req = MessageRequest(
        text="",
        chat_id=123,
        attachments=[
            AttachmentModel(type="location", latitude=32.08, longitude=34.78)
        ],
    )
    assert req.attachments[0].latitude == 32.08


def test_venue_attachment():
    from src.api.routes.message import MessageRequest, AttachmentModel
    req = MessageRequest(
        text="",
        chat_id=123,
        attachments=[
            AttachmentModel(
                type="location",
                latitude=32.08,
                longitude=34.78,
                title="Coffee Shop",
            )
        ],
    )
    assert req.attachments[0].title == "Coffee Shop"


def test_reply_context():
    from src.api.routes.message import MessageRequest, ReplyContextModel
    req = MessageRequest(
        text="yes do it",
        chat_id=123,
        reply_to=ReplyContextModel(text="Create task?", **{"from": "assistant"}),
    )
    assert req.reply_to.text == "Create task?"
    assert req.reply_to.from_role == "assistant"


def test_forward_context():
    from src.api.routes.message import MessageRequest, ForwardContextModel
    req = MessageRequest(
        text="Check this",
        chat_id=123,
        forwarded_from=ForwardContextModel(
            from_name="Alice",
            text="Interesting article",
            date="2026-03-04T14:00:00Z",
        ),
    )
    assert req.forwarded_from.from_name == "Alice"


def test_full_enriched_request():
    from src.api.routes.message import (
        MessageRequest, AttachmentModel, ReplyContextModel,
    )
    req = MessageRequest(
        text="Save this photo",
        chat_id=123,
        attachments=[
            AttachmentModel(
                type="photo",
                data="base64data",
                mime_type="image/jpeg",
                filename="photo.jpg",
            ),
            AttachmentModel(type="location", latitude=32.08, longitude=34.78),
        ],
        reply_to=ReplyContextModel(text="prev msg", **{"from": "user"}),
    )
    assert len(req.attachments) == 2
    assert req.reply_to is not None
```

**Step 2: Run test to verify it fails**

Run: `cd ~/dev/mazkir/apps/vault-server && source venv/bin/activate && python -m pytest tests/test_message_models.py -v`
Expected: FAIL — `AttachmentModel` etc. don't exist yet

**Step 3: Add Pydantic models**

Update `apps/vault-server/src/api/routes/message.py`:

```python
"""Natural language message endpoint — agent loop."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.auth import verify_api_key
from src.main import get_agent

router = APIRouter(tags=["message"], dependencies=[Depends(verify_api_key)])


class AttachmentModel(BaseModel):
    type: str  # "photo" | "location"
    # Photo fields
    data: str | None = None
    mime_type: str | None = None
    filename: str | None = None
    # Location fields
    latitude: float | None = None
    longitude: float | None = None
    title: str | None = None


class ReplyContextModel(BaseModel):
    text: str
    from_role: str = Field(alias="from")  # "user" | "assistant"

    model_config = {"populate_by_name": True}


class ForwardContextModel(BaseModel):
    from_name: str
    text: str
    date: str | None = None


class MessageRequest(BaseModel):
    text: str = ""
    chat_id: int = 0
    attachments: list[AttachmentModel] | None = None
    reply_to: ReplyContextModel | None = None
    forwarded_from: ForwardContextModel | None = None


class ConfirmationRequest(BaseModel):
    chat_id: int
    action_id: str
    response: str


@router.post("/message")
def handle_message(body: MessageRequest):
    agent = get_agent()
    if not agent:
        raise HTTPException(status_code=503, detail="Agent service not initialized (missing API key?)")

    # Convert Pydantic models to dicts for agent service
    attachments = None
    if body.attachments:
        attachments = [a.model_dump(by_alias=True, exclude_none=True) for a in body.attachments]

    reply_to = None
    if body.reply_to:
        reply_to = body.reply_to.model_dump(by_alias=True)

    forwarded_from = None
    if body.forwarded_from:
        forwarded_from = body.forwarded_from.model_dump(exclude_none=True)

    result = agent.handle_message(
        text=body.text,
        chat_id=body.chat_id,
        attachments=attachments,
        reply_to=reply_to,
        forwarded_from=forwarded_from,
    )
    return {
        "response": result.response,
        "awaiting_confirmation": result.awaiting_confirmation,
        "pending_action_id": result.pending_action_id,
    }


@router.post("/message/confirm")
def handle_confirmation(body: ConfirmationRequest):
    agent = get_agent()
    if not agent:
        raise HTTPException(status_code=503, detail="Agent service not initialized")

    result = agent.handle_confirmation(body.chat_id, body.action_id, body.response)
    return {
        "response": result.response,
        "awaiting_confirmation": result.awaiting_confirmation,
        "pending_action_id": result.pending_action_id,
    }
```

**Step 4: Run test to verify it passes**

Run: `cd ~/dev/mazkir/apps/vault-server && python -m pytest tests/test_message_models.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add apps/vault-server/src/api/routes/message.py apps/vault-server/tests/test_message_models.py
git commit -m "feat(vault-server): add enriched message Pydantic models for attachments/reply/forward"
```

---

### Task 5: Agent Service — Save Photos & Build Vision Messages

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py`
- Modify: `apps/vault-server/tests/test_agent_service.py`

**Context:**
- `handle_message()` currently takes `(text, chat_id)` — needs to accept optional `attachments`, `reply_to`, `forwarded_from`
- Photos saved to `data/media/{YYYY-MM-DD}/` (relative to project root, which is `vault_path.parent`)
- Claude API vision: user message content is a list with `{"type": "image", "source": {"type": "base64", ...}}` and `{"type": "text", ...}` blocks
- The `_build_system_prompt` needs a note about the `attach_to_daily` tool

**Step 1: Write the failing tests**

Add to `apps/vault-server/tests/test_agent_service.py`:

```python
class TestHandleMessageWithAttachments:
    def test_photo_saved_to_disk(self, agent, mock_services, tmp_path):
        """Photo attachment is saved to data/media/{date}/ directory."""
        claude = mock_services[0]
        vault = mock_services[1]

        # Point vault_path so media dir resolves
        vault.vault_path = tmp_path / "vault"
        vault.vault_path.mkdir()

        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Photo saved!"
        mock_response.content = [text_block]
        claude.create.return_value = mock_response

        import base64
        photo_bytes = base64.b64encode(b"fake-image-data").decode()

        result = agent.handle_message(
            text="Save this",
            chat_id=123,
            attachments=[{
                "type": "photo",
                "data": photo_bytes,
                "mime_type": "image/jpeg",
                "filename": "photo_2026-03-04_14-30-00.jpg",
            }],
        )

        assert result.response == "Photo saved!"
        # Verify Claude was called with image content block
        call_args = claude.create.call_args
        messages = call_args.kwargs.get("messages") or call_args[1].get("messages") or call_args[0][1] if len(call_args[0]) > 1 else call_args.kwargs["messages"]
        last_user_msg = [m for m in messages if m["role"] == "user"][-1]
        # Content should be a list (multi-block) when photo is present
        assert isinstance(last_user_msg["content"], list)

    def test_location_included_in_text(self, agent, mock_services):
        """Location coordinates appear in the text sent to Claude."""
        claude = mock_services[0]

        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Location noted!"
        mock_response.content = [text_block]
        claude.create.return_value = mock_response

        result = agent.handle_message(
            text="I'm here",
            chat_id=123,
            attachments=[{
                "type": "location",
                "latitude": 32.08,
                "longitude": 34.78,
            }],
        )

        assert result.response == "Location noted!"
        call_args = claude.create.call_args
        messages = call_args.kwargs.get("messages") or call_args[1].get("messages") or call_args[0][1] if len(call_args[0]) > 1 else call_args.kwargs["messages"]
        last_user_msg = [m for m in messages if m["role"] == "user"][-1]
        content = last_user_msg["content"]
        # Should contain location coordinates in text
        if isinstance(content, list):
            text_parts = [b["text"] for b in content if b.get("type") == "text"]
            assert any("32.08" in t and "34.78" in t for t in text_parts)
        else:
            assert "32.08" in content and "34.78" in content

    def test_reply_context_included(self, agent, mock_services):
        """Reply context appears in the text sent to Claude."""
        claude = mock_services[0]

        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Got it!"
        mock_response.content = [text_block]
        claude.create.return_value = mock_response

        result = agent.handle_message(
            text="yes do it",
            chat_id=123,
            reply_to={"text": "Should I create the task?", "from": "assistant"},
        )

        call_args = claude.create.call_args
        messages = call_args.kwargs.get("messages") or call_args[1].get("messages") or call_args[0][1] if len(call_args[0]) > 1 else call_args.kwargs["messages"]
        last_user_msg = [m for m in messages if m["role"] == "user"][-1]
        content = last_user_msg["content"]
        text_content = content if isinstance(content, str) else " ".join(
            b.get("text", "") for b in content if isinstance(b, dict)
        )
        assert "Should I create the task?" in text_content

    def test_plain_text_still_works(self, agent, mock_services):
        """Existing text-only flow is unchanged."""
        claude = mock_services[0]

        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Hello!"
        mock_response.content = [text_block]
        claude.create.return_value = mock_response

        result = agent.handle_message("hello", chat_id=123)
        assert result.response == "Hello!"
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/dev/mazkir/apps/vault-server && python -m pytest tests/test_agent_service.py::TestHandleMessageWithAttachments -v`
Expected: FAIL — `handle_message()` doesn't accept `attachments` parameter

**Step 3: Implement handle_message changes**

In `apps/vault-server/src/services/agent_service.py`:

1. Add imports at top:

```python
import base64
from pathlib import Path
```

2. Update `__init__` to accept a `data_path` (for media storage):

```python
def __init__(
    self,
    claude: ClaudeService,
    vault: VaultService,
    memory: MemoryService,
    calendar: Any = None,
    data_path: Path | None = None,
):
    self.claude = claude
    self.vault = vault
    self.memory = memory
    self.calendar = calendar
    self.data_path = data_path or (vault.vault_path.parent / "data")
    self.max_iterations = 10
    self.pending_confirmations: dict[str, PendingAction] = {}
    self.tools = self._register_tools()
```

3. Add a method to save photos:

```python
def _save_photo(self, attachment: dict) -> str | None:
    """Save a base64-encoded photo to data/media/{date}/ and return the path."""
    import datetime as dt
    today = dt.date.today().isoformat()
    media_dir = self.data_path / "media" / today
    media_dir.mkdir(parents=True, exist_ok=True)

    filename = attachment.get("filename", f"photo_{today}.jpg")
    file_path = media_dir / filename

    try:
        photo_bytes = base64.b64decode(attachment["data"])
        file_path.write_bytes(photo_bytes)
        return str(file_path.relative_to(self.data_path.parent))
    except Exception as e:
        logger.error(f"Failed to save photo: {e}")
        return None
```

4. Add a method to build enriched user message content:

```python
def _build_user_content(
    self,
    text: str,
    attachments: list[dict] | None = None,
    reply_to: dict | None = None,
    forwarded_from: dict | None = None,
) -> str | list[dict]:
    """Build user message content, potentially with image blocks for vision."""
    text_parts: list[str] = []
    image_blocks: list[dict] = []
    saved_photo_path: str | None = None

    if attachments:
        for att in attachments:
            if att["type"] == "photo" and att.get("data"):
                # Save photo to disk
                saved_photo_path = self._save_photo(att)

                # Add image block for Claude vision
                image_blocks.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": att.get("mime_type", "image/jpeg"),
                        "data": att["data"],
                    },
                })

                if saved_photo_path:
                    text_parts.append(f"[Photo saved to: {saved_photo_path}]")
                else:
                    text_parts.append("[Photo attachment failed to save]")

            elif att["type"] == "location":
                lat = att.get("latitude", 0)
                lng = att.get("longitude", 0)
                loc_str = f"[Location: {lat}, {lng}]"
                if att.get("title"):
                    loc_str = f"[Location: {lat}, {lng} — {att['title']}]"
                text_parts.append(loc_str)

    if reply_to:
        from_role = reply_to.get("from", "user")
        text_parts.append(f'[Replying to {from_role}: "{reply_to["text"]}"]')

    if forwarded_from:
        text_parts.append(
            f'[Forwarded from {forwarded_from["from_name"]}: "{forwarded_from["text"]}"]'
        )

    if text:
        text_parts.append(text)

    combined_text = "\n".join(text_parts)

    # If there are image blocks, return multi-content list
    if image_blocks:
        content: list[dict] = list(image_blocks)
        content.append({"type": "text", "text": combined_text})
        return content

    return combined_text
```

5. Update `handle_message` signature:

```python
def handle_message(
    self,
    text: str,
    chat_id: int,
    attachments: list[dict] | None = None,
    reply_to: dict | None = None,
    forwarded_from: dict | None = None,
) -> AgentResponse:
    """Main entry point: process a user message through the agent loop."""
    context = self.memory.assemble_context(chat_id)

    messages = []
    if context.summary:
        messages.append({"role": "user", "content": f"[Previous conversation summary: {context.summary}]"})
        messages.append({"role": "assistant", "content": "Understood, I have the prior context."})
    for msg in context.messages:
        messages.append({"role": msg["role"], "content": msg["content"]})

    # Build enriched user content (with image blocks if photo attached)
    user_content = self._build_user_content(
        text, attachments, reply_to, forwarded_from,
    )
    messages.append({"role": "user", "content": user_content})

    # For conversation log, build a text-only version (no base64)
    log_text = text
    if attachments:
        att_notes = []
        for att in attachments:
            if att["type"] == "photo":
                att_notes.append(f"photo: {att.get('filename', 'photo')}")
            elif att["type"] == "location":
                att_notes.append(f"location: {att.get('latitude')}, {att.get('longitude')}")
        if att_notes:
            log_text = f"({', '.join(att_notes)}) {text}".strip()
    if reply_to:
        log_text = f"(replying to {reply_to.get('from', 'user')}: \"{reply_to['text'][:50]}\") {log_text}".strip()

    system = self._build_system_prompt(context)

    return self._run_loop(chat_id, log_text, messages, system)
```

**Step 4: Run tests to verify they pass**

Run: `cd ~/dev/mazkir/apps/vault-server && python -m pytest tests/test_agent_service.py -v`
Expected: All PASS (both old and new tests)

**Step 5: Commit**

```bash
git add apps/vault-server/src/services/agent_service.py apps/vault-server/tests/test_agent_service.py
git commit -m "feat(vault-server): handle photo/location/reply/forward in agent loop with vision"
```

---

### Task 6: Agent Service — Register `attach_to_daily` Tool

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py`
- Modify: `apps/vault-server/src/services/vault_service.py`
- Modify: `apps/vault-server/tests/test_agent_service.py`

**Step 1: Write the failing test**

Add to `apps/vault-server/tests/test_agent_service.py`:

```python
class TestAttachToDaily:
    def test_attach_to_daily_tool_registered(self, agent):
        assert "attach_to_daily" in agent.tools
        assert agent.tools["attach_to_daily"]["risk"] == "write"

    def test_attach_to_daily_appends_to_note(self, agent, mock_services):
        vault = mock_services[1]

        vault.append_to_daily_section.return_value = {
            "path": "10-daily/2026-03-04.md",
            "section": "Notes",
        }

        result = agent._tool_attach_to_daily({
            "vault_path": "data/media/2026-03-04/photo_2026-03-04_14-30-00.jpg",
            "caption": "Dog walk stop",
            "wikilinks": ["City Watch"],
            "section": "Notes",
        })

        assert "path" in result
        vault.append_to_daily_section.assert_called_once()

    def test_attach_to_daily_with_location(self, agent, mock_services):
        vault = mock_services[1]

        vault.append_to_daily_section.return_value = {
            "path": "10-daily/2026-03-04.md",
            "section": "Notes",
        }

        result = agent._tool_attach_to_daily({
            "vault_path": "data/media/2026-03-04/photo.jpg",
            "caption": "Street photo",
            "location": {"lat": 32.08, "lng": 34.78, "name": "Tel Aviv"},
            "section": "Notes",
        })

        assert "path" in result
        call_args = vault.append_to_daily_section.call_args
        content = call_args[1].get("content") or call_args[0][1]
        assert "32.08" in content
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/dev/mazkir/apps/vault-server && python -m pytest tests/test_agent_service.py::TestAttachToDaily -v`
Expected: FAIL — `attach_to_daily` not registered

**Step 3: Add the tool registration and handler**

In `_register_tools()` in `agent_service.py`, add after `save_knowledge` (before `complete_task`):

```python
"attach_to_daily": {
    "schema": {
        "name": "attach_to_daily",
        "description": (
            "Attach a saved photo or file to today's daily note. "
            "Use after a photo has been saved to disk. "
            "Can include wikilinks (e.g. [[City Watch]]) and location coordinates."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "vault_path": {
                    "type": "string",
                    "description": "Path to saved attachment (from '[Photo saved to: ...]' context)",
                },
                "caption": {
                    "type": "string",
                    "description": "Caption/description for the attachment",
                },
                "wikilinks": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Wikilink targets to include, e.g. ['City Watch']",
                },
                "location": {
                    "type": "object",
                    "properties": {
                        "lat": {"type": "number"},
                        "lng": {"type": "number"},
                        "name": {"type": "string"},
                    },
                    "description": "Location coordinates to show with the attachment",
                },
                "section": {
                    "type": "string",
                    "description": "Daily note section to add under (default: 'Notes')",
                },
                "_confidence": {"type": "number"},
                "_reasoning": {"type": "string"},
            },
            "required": ["vault_path", "caption"],
        },
    },
    "handler": self._tool_attach_to_daily,
    "risk": "write",
},
```

Add the handler method:

```python
def _tool_attach_to_daily(self, params: dict) -> dict:
    import datetime as dt
    vault_path = params["vault_path"]
    caption = params["caption"]
    wikilinks = params.get("wikilinks", [])
    location = params.get("location")
    section = params.get("section", "Notes")

    now = dt.datetime.now()
    time_str = now.strftime("%H:%M")

    # Build markdown content block
    # Relative path from daily note (10-daily/) to project root
    lines = []
    lines.append(f"![{caption}](../../{vault_path})")
    meta_parts = [f"*{time_str} — {caption}*"]
    if wikilinks:
        meta_parts.append(" | ".join(f"[[{link}]]" for link in wikilinks))
    lines.append(" | ".join(meta_parts))
    if location:
        loc_parts = [f"{location['lat']}, {location['lng']}"]
        if location.get("name"):
            loc_parts.append(location["name"])
        lines.append(f"📍 {' — '.join(loc_parts)}")

    content = "\n".join(lines)

    result = self.vault.append_to_daily_section(section=section, content=content)
    daily_path = result.get("path", self.vault.get_daily_note_path())

    return {
        "path": daily_path,
        "section": section,
        "attachment": vault_path,
        "_items": [daily_path],
    }
```

**Step 4: Add `append_to_daily_section` to VaultService**

In `apps/vault-server/src/services/vault_service.py`, add this method (after `read_daily_note`):

```python
def append_to_daily_section(
    self,
    section: str = "Notes",
    content: str = "",
    date: Optional[datetime] = None,
) -> Dict:
    """Append content to a section of today's daily note.

    Creates the daily note if it doesn't exist.
    Finds the section heading (## Section) and appends content after it.
    """
    try:
        daily = self.read_daily_note(date)
    except FileNotFoundError:
        daily = self.create_daily_note(date)

    daily_content = daily["content"]
    section_header = f"## {section}"

    if section_header in daily_content:
        # Find the section and append after existing content
        # Look for the next section heading or end of file
        idx = daily_content.index(section_header)
        after_header = idx + len(section_header)

        # Find the next ## heading
        next_section = daily_content.find("\n## ", after_header)
        if next_section == -1:
            # No next section — append at end
            new_content = daily_content.rstrip() + "\n\n" + content + "\n"
        else:
            # Insert before next section
            before = daily_content[:next_section].rstrip()
            after = daily_content[next_section:]
            new_content = before + "\n\n" + content + "\n" + after
    else:
        # Section not found — append at end with heading
        new_content = daily_content.rstrip() + f"\n\n{section_header}\n\n{content}\n"

    path = self.get_daily_note_path(date)
    self.write_file(path, daily["metadata"], new_content)

    return {"path": path, "section": section}
```

**Step 5: Run tests to verify they pass**

Run: `cd ~/dev/mazkir/apps/vault-server && python -m pytest tests/test_agent_service.py -v`
Expected: All PASS

**Step 6: Write a test for `append_to_daily_section`**

Add to `apps/vault-server/tests/test_vault_service.py`:

```python
class TestAppendToDailySection:
    def test_appends_to_notes_section(self, vault_service, vault_path):
        # Create a daily note first
        vault_service.create_daily_note()
        result = vault_service.append_to_daily_section(
            section="Notes",
            content="![Dog walk](../../data/media/2026-03-04/photo.jpg)\n*14:30 — Dog walk*",
        )
        assert "path" in result

        # Read back and verify content was added
        daily = vault_service.read_daily_note()
        assert "Dog walk" in daily["content"]
        assert "photo.jpg" in daily["content"]

    def test_creates_daily_if_missing(self, vault_service, vault_path):
        result = vault_service.append_to_daily_section(
            section="Notes",
            content="Test content",
        )
        assert "path" in result
        daily = vault_service.read_daily_note()
        assert "Test content" in daily["content"]

    def test_appends_to_nonexistent_section(self, vault_service, vault_path):
        vault_service.create_daily_note()
        result = vault_service.append_to_daily_section(
            section="Photos",
            content="A photo here",
        )
        daily = vault_service.read_daily_note()
        assert "## Photos" in daily["content"]
        assert "A photo here" in daily["content"]
```

**Step 7: Run all vault-server tests**

Run: `cd ~/dev/mazkir/apps/vault-server && python -m pytest tests/ -v`
Expected: All PASS

**Step 8: Commit**

```bash
git add apps/vault-server/src/services/agent_service.py apps/vault-server/src/services/vault_service.py apps/vault-server/tests/test_agent_service.py apps/vault-server/tests/test_vault_service.py
git commit -m "feat(vault-server): add attach_to_daily tool and append_to_daily_section vault method"
```

---

### Task 7: Update Agent System Prompt

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py` (only `_build_system_prompt`)

**Step 1: Add attachment guidance to system prompt**

In `_build_system_prompt()`, add after the existing guidelines (around line 457):

```python
"- When the user sends a photo, you can SEE the image (vision). Describe what you see if relevant.",
"- Use attach_to_daily to save photos/attachments to the daily note with captions and wikilinks",
"- When a location is provided, include it when attaching to daily note",
"- Reply context [Replying to ...] shows what message the user is responding to — use it for context",
"- Forward context [Forwarded from ...] shows forwarded messages — treat as shared information",
```

**Step 2: Run existing tests to verify nothing breaks**

Run: `cd ~/dev/mazkir/apps/vault-server && python -m pytest tests/test_agent_service.py -v`
Expected: All PASS

**Step 3: Commit**

```bash
git add apps/vault-server/src/services/agent_service.py
git commit -m "feat(vault-server): add attachment/vision guidance to agent system prompt"
```

---

### Task 8: Update Memory Service Conversation Log

**Files:**
- Modify: `apps/vault-server/src/services/memory_service.py` (only `save_turn`)
- Already tested implicitly via agent_service tests, but verify

The `save_turn` method already receives the `log_text` which we enriched in Task 5 with attachment/reply metadata prefixes like `(photo: photo.jpg, location: 32.08, 34.78)` and `(replying to assistant: "...")`. No changes needed to `save_turn` itself — the enriched `log_text` from `handle_message` already includes the metadata.

**Step 1: Verify conversation log format with a test**

Add to `apps/vault-server/tests/test_memory_service.py`:

```python
def test_save_turn_with_attachment_metadata(memory_service, vault_path):
    """Attachment metadata in user message is preserved in conversation log."""
    memory_service.save_turn(
        chat_id=123,
        user_msg='(photo: photo_2026-03-04_14-30.jpg, location: 32.08, 34.78) Save this to daily note',
        assistant_msg="Photo attached to daily note!",
        items_referenced=["10-daily/2026-03-04.md"],
    )

    conversation = memory_service.load_conversation(123)
    assert len(conversation["messages"]) == 2
    user_msg = conversation["messages"][0]
    assert "photo" in user_msg["content"]
    assert "32.08" in user_msg["content"]
```

**Step 2: Run the test**

Run: `cd ~/dev/mazkir/apps/vault-server && python -m pytest tests/test_memory_service.py -v -k "attachment_metadata"`
Expected: PASS (no code changes needed — just validating)

**Step 3: Commit**

```bash
git add apps/vault-server/tests/test_memory_service.py
git commit -m "test(vault-server): verify attachment metadata persisted in conversation log"
```

---

### Task 9: Update main.py Initialization

**Files:**
- Modify: `apps/vault-server/src/main.py`

**Step 1: Pass data_path to AgentService**

In `main.py`, update the AgentService initialization (line 69-74):

```python
# From:
if claude:
    agent = AgentService(
        claude=claude,
        vault=vault,
        memory=memory,
        calendar=calendar,
    )

# To:
if claude:
    agent = AgentService(
        claude=claude,
        vault=vault,
        memory=memory,
        calendar=calendar,
        data_path=settings.vault_path.parent / "data",
    )
```

**Step 2: Verify server starts**

Run: `cd ~/dev/mazkir/apps/vault-server && source venv/bin/activate && timeout 5 python -m uvicorn src.main:app --port 8000 || true`
Expected: Server starts without errors (times out after 5s which is fine)

**Step 3: Commit**

```bash
git add apps/vault-server/src/main.py
git commit -m "feat(vault-server): pass data_path to AgentService for media storage"
```

---

### Task 10: End-to-End Smoke Test

**Step 1: Run all tests across the monorepo**

Run: `cd ~/dev/mazkir && npx turbo test`
Expected: All test suites PASS

**Step 2: Fix any failures**

Address test failures from integration. Common issues:
- Import path changes
- Type mismatches between shared-types and bot
- Mock setup in agent_service tests needing `data_path`

**Step 3: Manual verification checklist**

If vault-server + bot are running locally:
1. Send a text message → should work as before
2. Send a photo with caption → bot should download, base64, send to server
3. Send a location → coordinates should appear in agent context
4. Reply to a bot message → reply context should be included
5. Check `data/media/` for saved photos
6. Check daily note for attached content

**Step 4: Final commit (if any fixes)**

```bash
git add -A
git commit -m "fix: address integration issues from rich messages feature"
```
