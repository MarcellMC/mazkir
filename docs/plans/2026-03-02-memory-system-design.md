# Mazkir Memory System — Design Document

**Date:** 2026-03-02
**Status:** Approved
**Scope:** Three-tier memory system + agentic loop with human-in-the-loop for vault-server

## Problem

Every NL message through Telegram is atomic and stateless. The system parses intent, executes one action, responds, and forgets. This means:

- No multi-step creation ("create task" → "set it to high priority")
- No context recall ("mark that task done" — system doesn't know what "that" is)
- No conversational flow ("what tasks do I have?" → "complete the first one")
- No knowledge persistence (ideas, preferences, and patterns are lost)

## Solution

Replace the stateless intent-parse-then-route pattern with a **Claude tool-use agent loop** backed by a **three-tier memory system**, all stored in the Obsidian vault.

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                   Telegram Client                    │
│  (thin UI layer — minor changes only)                │
└──────────────────────┬──────────────────────────────┘
                       │ POST /message {text, chat_id}
                       ▼
┌─────────────────────────────────────────────────────┐
│                   Vault Server                       │
│                                                      │
│  ┌─────────────────────────────────────────────┐    │
│  │            AgentService (new)                │    │
│  │  message + history + tools → Claude          │    │
│  │  ← tool_use? execute → feed back → repeat   │    │
│  │  ← end_turn? return response to user         │    │
│  │                                               │    │
│  │  Confidence gate:                             │    │
│  │  high → auto-execute tool calls              │    │
│  │  low  → return confirmation request to user  │    │
│  └──────┬──────────┬──────────┬────────────────┘    │
│         │          │          │                       │
│    ┌────▼───┐ ┌────▼────┐ ┌──▼──────────┐          │
│    │ Memory │ │  Vault  │ │  Calendar   │          │
│    │Service │ │ Service │ │  Service    │          │
│    │ (new)  │ │(exists) │ │  (exists)   │          │
│    └────┬───┘ └─────────┘ └─────────────┘          │
│         │                                            │
│    ┌────▼─────────────────────────────────┐         │
│    │         Three Memory Tiers            │         │
│    │                                       │         │
│    │  Short: conversation window           │         │
│    │  Mid:   vault state (tasks/habits/..) │         │
│    │  Long:  knowledge notes + graph       │         │
│    └───────────────────────────────────────┘         │
└─────────────────────────────────────────────────────┘
                       │
                       ▼
              ┌─────────────────┐
              │  Obsidian Vault  │
              │  (all storage)   │
              └─────────────────┘
```

**Key changes from current system:**

1. `/message` route becomes an agent loop instead of intent-parse-then-switch
2. New `MemoryService` manages all three memory tiers
3. New `AgentService` runs the tool-use loop with confidence gating
4. `ClaudeService` simplified — no more `parse_intent()`, just raw Claude API calls
5. Existing routes (`/tasks`, `/habits`, etc.) remain unchanged for slash commands
6. Telegram client gets minor updates: passes `chat_id`, handles confirmation prompts

## Memory Tiers

### Short-Term — Conversation Window

Recent messages between user and Mazkir. Stored per chat per day.

**Storage:** `memory/00-system/conversations/{YYYY-MM-DD}/{chat_id}.md`

**Mechanics:**
- Sliding window of last ~20 messages sent to Claude in the `messages` array
- When conversation exceeds window, oldest half gets summarized by Claude (haiku, cheap) into a `summary` frontmatter field
- Summary is injected as the first message pair in the conversation
- No hard session timeout — new day starts a new file, but yesterday's summary carries forward
- `items_referenced` tracks which vault items were touched (feeds the graph)

**Schema:**

```yaml
---
type: conversation
chat_id: 123456789
date: 2026-03-02
started: 2026-03-02T09:15:00-06:00
last_active: 2026-03-02T09:32:00-06:00
message_count: 8
summary: "Completed gym habit (streak 15), created buy-groceries task, updated due date"
tags: [gym, groceries, tasks]
items_referenced: ["20-habits/gym.md", "40-tasks/active/buy-groceries.md"]
---
```

Messages stored as markdown sections below frontmatter:

```markdown
### 09:15 [user]
I just finished gym

### 09:15 [assistant]
Gym completed! Streak: 14 → 15 days. +5 tokens.
```

**What this enables:** "mark that task done", "set it to high priority", "actually make it due Friday instead"

### Mid-Term — Vault State

Active tasks, habits, goals, daily notes, system templates. Already exists — no new storage.

**What changes:** MemoryService assembles a vault context snapshot for each agent loop call. Not everything goes into context — only relevant items:

1. Items referenced in current conversation (always)
2. Items due today / overdue (always)
3. Active habits as compact list — names + streaks (always)
4. Today's daily note summary + token balance (always)
5. Recently modified items in last 24h (if space permits)
6. Everything else available via tools — Claude can call `list_tasks`, etc.

Snapshot goes into the **system prompt**, not messages.

### Long-Term — Knowledge + Graph

Persistent notes, ideas, learned preferences, and connections between them.

**Storage:**

```
memory/00-system/preferences/     # system-inferred user patterns
memory/60-knowledge/
├── notes/                        # user-captured ideas, facts, references
└── insights/                     # AI-generated connections
```

- `preferences/` in `00-system/` — internal operational data (not user-browsable)
- `notes/` and `insights/` in `60-knowledge/` — user-facing, browsable in Obsidian

**Knowledge note schema:**

```yaml
---
type: knowledge
name: Dentist location
created: 2026-03-02
updated: 2026-03-02
tags: [health, locations]
links: ["[[dr-garcia]]"]
source: conversation
source_ref: "00-system/conversations/2026-03-02/123456789.md"
---

Dentist is on Av. Roma 1234, Dr. Garcia. Appointments usually Thursdays.
```

**Preference schema:**

```yaml
---
type: knowledge
name: Task creation defaults
created: 2026-02-20
updated: 2026-03-02
tags: [preferences, tasks]
links: []
source: inferred
confidence: 0.8
observations: 12
---

- Default priority is 3 when not specified
- Grocery tasks are always priority 1
- Work tasks get category "work", everything else "personal"
```

**Insight schema:**

```yaml
---
type: knowledge
name: Health routine gap
created: 2026-03-02
updated: 2026-03-02
tags: [health, insights]
links: ["[[gym]]", "[[morning-routine]]", "[[meal-prep]]"]
source: inferred
confidence: 0.7
---

User consistently creates meal-related tasks after gym (observed 8 times)
but has no meal-prep habit. A recurring habit might reduce repeated task creation.
```

### Graph Index

MemoryService maintains an in-memory adjacency map of all vault nodes. Built from `[[wikilinks]]`, tags, and frontmatter `links`/`items_referenced` fields.

**Built at startup** by scanning all vault markdown files. Updated incrementally on writes.

**Exposed as Claude tools:**
- `search_knowledge(query)` — scan titles + tags + content for relevance
- `get_related(topic, depth)` — BFS traversal of graph neighbors
- `save_knowledge(name, content, tags, links)` — create knowledge note
- `get_most_connected(tag, limit)` — nodes with most edges

**Semantic search — phased:**
- Phase 1: keyword + tag matching + graph neighbors. Good enough for <200 notes.
- Phase 2: embedding vectors for similarity search when vault grows.

## Agent Loop

### Flow

```
User message arrives
    │
    ▼
MemoryService.assemble_context(chat_id)
    │  → load conversation history (sliding window)
    │  → build vault snapshot (relevant items)
    │  → gather relevant knowledge (graph + preferences)
    ▼
Build Claude API call:
    system = vault_snapshot + knowledge + guidelines
    messages = [summary?] + conversation_history + new_message
    tools = all registered tools
    │
    ▼
┌─ Loop (max 10 iterations) ─────────────────┐
│  response = claude.create(system, messages, tools)
│                                              │
│  stop_reason == "end_turn"?                  │
│    → break, return text response             │
│                                              │
│  stop_reason == "tool_use"?                  │
│    → confidence gate each tool call          │
│    → if all pass: execute, feed results back │
│    → if any fail: pause, request confirmation│
└──────────────────────────────────────────────┘
    │
    ▼
MemoryService.save_turn(chat_id, user_msg, assistant_msg)
MemoryService.summarize_and_decay(chat_id)  # if window exceeded
```

### Context Placement

| Content | Where | Why |
|---------|-------|-----|
| Conversation history | `messages[]` | Claude's native turn format |
| Decayed summary | `messages[]` (first turns) | Still conversation, just compressed |
| Vault snapshot | `system` prompt | Ambient context |
| Knowledge/preferences | `system` prompt | Ambient context |
| Tool definitions | `tools` parameter | Claude's native tool API |

### Tool Registry

| Tool | Maps to | Risk |
|------|---------|------|
| `list_tasks` | `vault.list_active_tasks()` | safe |
| `list_habits` | `vault.list_active_habits()` | safe |
| `list_goals` | `vault.list_active_goals()` | safe |
| `get_daily` | `vault.read_daily_note()` | safe |
| `get_tokens` | `vault.read_token_ledger()` | safe |
| `get_calendar` | `calendar.get_todays_events()` | safe |
| `create_task` | `vault.create_task()` | write |
| `create_habit` | `vault.create_habit()` | write |
| `create_goal` | `vault.create_goal()` | write |
| `complete_task` | `vault.find_task_by_name()` + `vault.complete_task()` | destructive |
| `complete_habit` | habit completion logic | destructive |
| `update_item` | `vault.update_file()` | write |
| `search_knowledge` | `memory.search_knowledge()` | safe |
| `get_related` | `memory.get_related()` | safe |
| `save_knowledge` | `memory.save_knowledge()` | write |
| `sync_to_calendar` | `calendar.sync_habit/task()` | write |

### Confidence Gate

Two signals combined:

**1. Static tool risk classification:** `safe`, `write`, `destructive`

**2. Dynamic confidence from Claude:** System prompt instructs Claude to include `_confidence` (0-1) and `_reasoning` in every write/destructive tool call.

**Decision matrix:**

| Tool risk | Confidence >= 0.85 | Confidence < 0.85 |
|-----------|--------------------|--------------------|
| safe | auto-execute | auto-execute |
| write | auto-execute | confirm |
| destructive | auto-execute | confirm |

**Confirmation flow:** When gate triggers, AgentService stores the pending tool calls, returns a confirmation prompt to the user. User's response re-enters the loop — "yes" executes pending calls and resumes, anything else gets fed to Claude as context to adjust.

### Safety

- Max 10 loop iterations — hard cap
- Token budget tracking — inject "wrap up" message if approaching limit
- Tool errors returned to Claude as results — it can retry or report
- Overall request timeout (30s)

## New Services

### MemoryService

```
memory_service.py

__init__(vault, vault_path, timezone)
initialize()                    # build graph index at startup

# Context assembly
assemble_context(chat_id)       # → ConversationContext

# Conversation management
load_conversation(chat_id)      # → messages + summary
save_turn(chat_id, user, assistant, items_referenced)
summarize_and_decay(chat_id)    # compress old messages

# Knowledge CRUD
save_knowledge(name, content, tags, links, source)
search_knowledge(query, limit)
update_preference(name, observation)

# Graph
get_related(topic, depth)
get_most_connected(tag, limit)
_rebuild_graph()
_update_graph_for_file(path, metadata, content)
```

### AgentService

```
agent_service.py

__init__(claude, vault, memory, calendar)

handle_message(text, chat_id)           # → AgentResponse
handle_confirmation(chat_id, action_id, user_response) # → AgentResponse

_register_tools()                       # → tool registry
_execute_tool(name, params)             # → tool result
_check_confidence(name, params)         # → bool
_build_system_prompt(context)           # → str
_request_confirmation(...)              # → AgentResponse (paused)
_continue_loop(chat_id, messages)       # → AgentResponse (resumed)
```

### ClaudeService — simplified

Remove `parse_intent()`. Keep as thin API wrapper:

- `create(system, messages, tools, model, max_tokens)` — tool-use API call
- `complete(prompt, system, model, max_tokens)` — simple single-turn (for summarization)

## Telegram Client Changes

Minimal changes to keep the client thin:

1. **`send_message(text, chat_id)`** — add `chat_id` parameter
2. **`send_confirmation(chat_id, action_id, response)`** — new method
3. **NL handler** — add confirmation routing via `pending_confirmations: dict[int, str]` (chat_id → action_id)
4. **Remove `_format_nl_response()`** — Claude generates formatted responses directly
5. **Slash commands** — unchanged

## Vault Structure Changes

New folders and templates:

```
memory/
├── 00-system/
│   ├── templates/
│   │   ├── _conversation_.md    # new
│   │   └── _knowledge_.md       # new
│   ├── conversations/            # new — short-term memory
│   │   └── {YYYY-MM-DD}/
│   │       └── {chat_id}.md
│   └── preferences/              # new — inferred user patterns
├── 60-knowledge/                  # new — user-facing knowledge
│   ├── notes/
│   └── insights/
```

Update `memory/AGENTS.md` with conversation + knowledge schemas.

## File Change Summary

| File | Change |
|------|--------|
| `vault-server/src/services/claude_service.py` | Simplify: remove `parse_intent()`, add `create()` |
| `vault-server/src/services/memory_service.py` | **New**: context assembly, conversations, knowledge, graph |
| `vault-server/src/services/agent_service.py` | **New**: agent loop, tool registry, confidence gate |
| `vault-server/src/api/routes/message.py` | Replace 240-line intent routing with 2 endpoints |
| `vault-server/src/main.py` | Add MemoryService + AgentService init in lifespan |
| `telegram-py-client/src/bot/handlers.py` | Simplify NL handler, add confirmation routing |
| `telegram-py-client/src/api_client.py` | Add `chat_id` to `send_message()`, add `send_confirmation()` |
| `memory/AGENTS.md` | Add new schemas |
| `memory/00-system/templates/` | Add `_conversation_.md`, `_knowledge_.md` |

**Untouched:** `vault_service.py`, `calendar_service.py`, all existing routes, all slash command handlers.

## Future Extensions

- **Autonomous agents:** Same tool definitions, different loop controller with checkpoint-based approval
- **Embeddings for semantic search:** Phase 2 when vault grows past ~200 notes
- **Preference auto-generation:** Periodic batch job that analyzes conversation history to update preferences
- **Telegram Mini App:** WebApp can share the same agent API via `/message`
