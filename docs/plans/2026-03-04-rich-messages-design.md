# Rich Messages Design — Attachments, Reply Context, Forwarded Messages

**Date:** 2026-03-04
**Status:** Approved

## Problem

The Telegram bot only handles `message:text` events. Photos, locations, reply context, and forwarded messages are silently ignored. This prevents workflows like: send a photo during a dog walk → save to daily note with location and `[[City Watch]]` wikilink.

## Goals

1. Support photo attachments — download, save to disk, pass to Claude via vision
2. Support location messages — extract coordinates, pass to agent
3. Support reply/quote context — include quoted message in agent context + conversation log
4. Support forwarded message context — include forward origin metadata
5. Agent (Claude) decides what to do with all enriched context via existing tool-use loop

## Non-Goals

- Other attachment types (documents, contacts, voice, video, stickers) — future iteration
- Telegram Web App changes
- New vault schemas or templates

## Architecture: Approach 1 — Extend `/message` with Enriched Payload

Single endpoint, backward-compatible. Bot extracts rich context from Telegram messages, downloads photos, base64-encodes, and sends everything in one POST to vault-server. Server saves photos to disk, builds multi-content Claude messages (image blocks + text), and lets the agent loop decide actions.

## Data Model

### Shared Types (TypeScript + Python mirrors)

```typescript
interface MessageRequest {
  text: string;           // caption or message text (can be empty for photo-only)
  chat_id: number;

  attachments?: Attachment[];
  reply_to?: ReplyContext;
  forwarded_from?: ForwardContext;
}

interface Attachment {
  type: "photo" | "location";

  // Photo fields
  data?: string;          // base64-encoded image bytes
  mime_type?: string;      // "image/jpeg"
  filename?: string;       // "photo_2026-03-04_14-30.jpg"

  // Location fields
  latitude?: number;
  longitude?: number;
  title?: string;          // venue name if sent as venue
}

interface ReplyContext {
  text: string;            // text of the message being replied to
  from: "user" | "assistant";
}

interface ForwardContext {
  from_name: string;       // forwarded from user/channel name
  text: string;            // forwarded message text
  date?: string;           // original message date
}
```

## Bot-Side Extraction

The NL message handler expands from `message:text` to also handle `message:photo` and `message:location`.

**Single handler function flow:**
1. Extract `text` = `message.text || message.caption || ""`
2. Extract attachments:
   - Photo: get largest photo size → `bot.api.getFile()` → download bytes → base64
   - Location: extract lat/lng/title from `message.location` or `message.venue`
3. Extract reply context:
   - If `message.reply_to_message` exists → grab its text + determine role (bot's own messages = "assistant", everything else = "user")
4. Extract forward context:
   - If `message.forward_origin` exists → grab sender name + text + date
5. Send enriched payload to `api.sendMessage()`

**Photo download:** grammY `bot.api.getFile(file_id)` → fetch `https://api.telegram.org/file/bot<token>/<file_path>` → base64-encode.

**Filename:** `photo_{YYYY-MM-DD}_{HH-mm-ss}.jpg` from message timestamp.

**Confirmation flow** unchanged — only triggers on text replies to pending actions.

## Server-Side Processing

### 1. Save Photos to Disk

Photos saved to `data/media/{YYYY-MM-DD}/` before the agent loop runs. This directory is already gitignored (via `data/`).

```
photo_2026-03-04_14-30.jpg
  → data/media/2026-03-04/photo_2026-03-04_14-30.jpg
```

### 2. Build Claude Message with Vision

The user message sent to Claude becomes a multi-content-block message:

```python
content = []

# Image block (for vision)
if photo_attachment:
    content.append({
        "type": "image",
        "source": {"type": "base64", "media_type": "image/jpeg", "data": base64_data}
    })

# Text block with all context
text_parts = []
if reply_to:
    text_parts.append(f'[Replying to {reply_to.from_role}: "{reply_to.text}"]')
if forwarded_from:
    text_parts.append(f'[Forwarded from {forwarded_from.from_name}: "{forwarded_from.text}"]')
if location_attachments:
    text_parts.append(f"[Location: {lat}, {lng}]")
if photo_saved_path:
    text_parts.append(f"[Photo saved to: {photo_saved_path}]")
if user_text:
    text_parts.append(user_text)

content.append({"type": "text", "text": "\n".join(text_parts)})
```

### 3. New Agent Tool: `attach_to_daily`

```python
{
    "name": "attach_to_daily",
    "description": "Attach a saved file to today's daily note with optional wikilinks and location",
    "params": {
        "vault_path": "path to the saved attachment relative to project root",
        "caption": "description to show alongside the attachment",
        "wikilinks": ["list of wikilink targets"],  # e.g. ["City Watch"]
        "location": {"lat": float, "lng": float, "name": str},  # optional
        "section": "which daily note section to add under (default: Notes)"
    },
    "risk": "write"  # confidence gate applies
}
```

Appends to daily note using standard markdown image syntax with relative path:

```markdown
## Notes

![Dog walk stop](../../data/media/2026-03-04/photo_2026-03-04_14-30.jpg)
*14:30 — Dog walk stop* | [[City Watch]]
📍 32.0853, 34.7818
```

### 4. Conversation Log

Reply and attachment metadata persisted in conversation file:

```markdown
### 14:30 [user] (replying to assistant)
> You completed 3 habits today
Also mark the dog walk done

### 14:31 [user] (photo: photo_2026-03-04_14-30.jpg, location: 32.08, 34.78)
Save this to daily note, link to [[City Watch]]
```

## Error Handling

- **Photo without caption:** Claude sees the image via vision, can describe and ask what to do or infer from conversation context.
- **Location without photo:** Coordinate metadata passed to Claude. Agent can attach to daily note or use for merged events.
- **Photo + location in same message:** Telegram sends these as separate message types. Conversation context connects them via sliding window.
- **Large photos:** Telegram compresses; largest size ~1-2MB. Base64 adds ~33% → ~2.7MB max. Acceptable for local transport.
- **Failed download:** Skip photo, send text only, append `[Photo attachment failed to download]`.
- **Reply to non-text message:** Include `[Replying to assistant: (photo response)]`.

## Scope of Changes

| Package | File | Change |
|---------|------|--------|
| `shared-types` | `src/message.ts` | Add `Attachment`, `ReplyContext`, `ForwardContext` interfaces; extend `MessageRequest` |
| `telegram-bot` | `src/conversations/message.ts` | Handle `message:photo`, `message:location`; extract attachments, reply, forward context; download + base64 photos |
| `telegram-bot` | `src/api/client.ts` | Update `sendMessage` to accept enriched payload |
| `vault-server` | `src/api/routes/message.py` | Expand `MessageRequest` Pydantic model |
| `vault-server` | `src/services/agent_service.py` | Save photos to `data/media/`; build multi-content Claude messages; register `attach_to_daily` tool; handle reply/forward in text block |
| `vault-server` | `src/services/vault_service.py` | Add method to append content to a daily note section |
| `vault-server` | `src/services/memory_service.py` | Persist reply/forward/attachment metadata in conversation log |

**No changes to:** `telegram-web-app`, vault schemas, templates, existing agent tools.
