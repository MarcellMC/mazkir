# Mazkir Session Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire Mazkir to `session.sh` so a reported bug becomes either an autonomous session (monitored, notified, auto-cleaned) or a hand-off session you attach to from Claude Mobile — chosen with Telegram buttons at the confirmation gate.

**Architecture:** `spawn_container` stops building `docker run` arguments and shells out to `session.sh`, making the automated and manual paths one implementation. The confirmation gate gains a generic `confirmation_choices` field so the server names the options and the bot renders whatever it is given, keeping the bot a presentation layer. Autonomous and hand-off diverge only in the launch mode, the brief text, and whether anything watches the result.

**Tech Stack:** Python (FastAPI, pytest), TypeScript (grammY, vitest), bash, Docker.

**Spec:** `docs/superpowers/specs/2026-08-08-agent-sessions-design.md`
**Depends on:** `docs/superpowers/plans/2026-08-08-devcontainer-foundation.md` (complete — `session.sh` exists with `provision`, `launch`, `list`, `clean`, `start`).

## Global Constraints

- The bot stays a presentation layer: it renders whatever choices the server names and knows nothing about coding sessions.
- Secrets never appear in argv. `session.sh` owns credential handling; nothing here reintroduces `-e`.
- Hand-off sessions get **no** poller entry, **no** completion notification, and **no** automatic cleanup.
- Autonomous cleanup calls `session.sh clean` — never a second `rmtree` implementation.
- Sessions live in `~/dev/agent-sessions/`; branches are `coding-agent/<name>`.
- Python tests: `cd apps/vault-server && source venv/bin/activate && python -m pytest`.
- Bot tests: `cd apps/telegram-bot && npx vitest run`.

---

### Task 1: Stop `sendRich` from discarding the inline keyboard

`sendRich`'s fallback calls `ctx.reply(text)` with no second argument, dropping `extra` — which is where `reply_markup` rides. A rejected rich payload would strip the buttons and leave no way to choose a lane. It also never logs why the send failed, which is why a missing env var was undiagnosable.

**Files:**
- Modify: `apps/telegram-bot/src/bot-utils/send-rich.ts`
- Create: `apps/telegram-bot/tests/send-rich.test.ts`

**Interfaces:**
- Produces: `sendRich(ctx, msg, extra?)` — on fallback, passes `extra` through to `ctx.reply` and logs the rejection at WARN.

- [ ] **Step 1: Write the failing test**

Create `apps/telegram-bot/tests/send-rich.test.ts`:

```typescript
import { describe, it, expect, vi } from "vitest";
import { sendRich } from "../src/bot-utils/send-rich.js";

function ctxThatRejectsRich() {
  const reply = vi.fn().mockResolvedValue(undefined);
  return {
    ctx: {
      replyWithRichMessage: vi.fn().mockRejectedValue(new Error("rich rejected")),
      reply,
    } as never,
    reply,
  };
}

describe("sendRich", () => {
  it("keeps reply_markup when the rich payload is rejected", async () => {
    const { ctx, reply } = ctxThatRejectsRich();
    const extra = { reply_markup: { inline_keyboard: [[{ text: "Autonomous", callback_data: "x" }]] } };

    await sendRich(ctx, { markdown: "pick a lane" }, extra);

    expect(reply).toHaveBeenCalledTimes(1);
    expect(reply.mock.calls[0]![1]).toEqual(extra);
  });

  it("still sends the text when there is no extra", async () => {
    const { ctx, reply } = ctxThatRejectsRich();

    await sendRich(ctx, { markdown: "hello" });

    expect(reply).toHaveBeenCalledTimes(1);
    expect(reply.mock.calls[0]![0]).toContain("hello");
  });

  it("does not fall back when the rich payload succeeds", async () => {
    const reply = vi.fn();
    const ctx = {
      replyWithRichMessage: vi.fn().mockResolvedValue(undefined),
      reply,
    } as never;

    await sendRich(ctx, { markdown: "ok" });

    expect(reply).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/telegram-bot && npx vitest run tests/send-rich.test.ts`
Expected: "keeps reply_markup" FAILS — `reply` is called with one argument, so `calls[0][1]` is `undefined`.

- [ ] **Step 3: Pass `extra` through and log the cause**

In `apps/telegram-bot/src/bot-utils/send-rich.ts`, replace the `catch` block:

```typescript
  } catch (err) {
    markActiveSpanError(err);
    // `extra` carries reply_markup. Dropping it here would strip an inline
    // keyboard from the fallback, leaving a prompt with no way to answer it.
    logger.warn(
      { event_type: "rich_message_fallback", err: String(err) },
      "rich_message_fallback",
    );
    await ctx.reply(richToPlainText(msg), extra as never);
  }
```

Add the logger import at the top of the file, matching the pattern used elsewhere in the bot:

```typescript
import { logger } from "../logger.js";
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/telegram-bot && npx vitest run`
Expected: all suites pass, including the 3 new cases.

- [ ] **Step 5: Commit**

```bash
git add apps/telegram-bot/src/bot-utils/send-rich.ts apps/telegram-bot/tests/send-rich.test.ts
git commit -m "fix(bot): keep reply_markup and log the cause when rich send fails

sendRich's fallback called ctx.reply with no second argument, discarding
extra -- which carries reply_markup. A rejected rich payload would strip
the inline keyboard, leaving a prompt the user cannot answer. It also
never logged why the send was rejected, which is why a missing env var
was undiagnosable."
```

---

### Task 2: Add `confirmation_choices` to the server's confirmation contract

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py`
- Modify: `apps/vault-server/src/api/routes/message.py`
- Modify: `apps/vault-server/tests/test_skill_loop.py`

**Interfaces:**
- Produces: `AgentResponse.confirmation_choices: list[dict] | None` — each entry `{"value": str, "label": str}`. Both `/message` and `/message/confirm` echo it. `None` (the default) means the client falls back to free-text yes/no.

- [ ] **Step 1: Write the failing test**

Append to `apps/vault-server/tests/test_skill_loop.py`:

```python
def test_agent_response_carries_confirmation_choices(mock_services, monkeypatch):
    """The server names the options; the bot renders whatever it is given
    and stays ignorant of coding sessions."""
    from src.services.agent_service import AgentService, AgentResponse
    claude, vault, memory, calendar, events = mock_services

    skill = _mk_skill("engineering", ["propose_coding_session"])
    skill_registry = MagicMock()
    skill_registry.list.return_value = [skill]
    skill_registry.get.side_effect = lambda n: skill if n == "engineering" else None
    router = MagicMock()
    router.pick.return_value = MagicMock(skill="engineering", reason="bug")

    agent = AgentService(
        claude=claude, vault=vault, memory=memory, calendar=calendar, events=events,
        skill_registry=skill_registry, router=router,
    )
    choices = [
        {"value": "autonomous", "label": "Autonomous"},
        {"value": "handoff", "label": "Hand-off"},
    ]
    monkeypatch.setattr(
        agent, "_run_agent_turn",
        lambda **kwargs: AgentResponse(
            response="pick a lane",
            awaiting_confirmation=True,
            pending_action_id="act_1",
            confirmation_choices=choices,
        ),
    )

    result = agent.handle_message("the /day command is broken", chat_id=42)

    assert result.confirmation_choices == choices


def test_agent_response_defaults_to_no_choices(mock_services, monkeypatch):
    from src.services.agent_service import AgentService, AgentResponse
    claude, vault, memory, calendar, events = mock_services

    skill = _mk_skill("mazkir", ["list_tasks"])
    skill_registry = MagicMock()
    skill_registry.list.return_value = [skill]
    skill_registry.get.side_effect = lambda n: skill if n == "mazkir" else None
    router = MagicMock()
    router.pick.return_value = MagicMock(skill="mazkir", reason="")

    agent = AgentService(
        claude=claude, vault=vault, memory=memory, calendar=calendar, events=events,
        skill_registry=skill_registry, router=router,
    )
    monkeypatch.setattr(
        agent, "_run_agent_turn", lambda **kwargs: AgentResponse(response="hi"),
    )

    result = agent.handle_message("hello", chat_id=42)

    assert result.confirmation_choices is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_skill_loop.py -k confirmation_choices -v`
Expected: FAILS with `TypeError: AgentResponse.__init__() got an unexpected keyword argument 'confirmation_choices'`.

- [ ] **Step 3: Thread the field through**

In `apps/vault-server/src/services/agent_service.py`, add to the `AgentResponse` dataclass (after `pending_action_id`):

```python
    confirmation_choices: list[dict] | None = None
```

In `skill_executor.py`, add to `SkillExecutorResult`:

```python
    confirmation_choices: list[dict] | None = None
```

Extend `LoopOutcome` with a fourth field:

```python
class LoopOutcome(NamedTuple):
    response_text: str
    stop_reason: str
    pending_action_id: str | None = None
    confirmation_choices: list[dict] | None = None
```

In `SkillExecutor.run`, capture it alongside `pending_action_id`:

```python
                    pending_action_id = outcome.pending_action_id
                    confirmation_choices = outcome.confirmation_choices
```

Initialize `confirmation_choices = None` next to `pending_action_id: str | None = None` before the loop, and pass it into the returned `SkillExecutorResult`.

In `agent_service.py`'s `_run_loop`, carry it out:

```python
        if result.awaiting_confirmation:
            return LoopOutcome(
                result.response, "needs_confirmation",
                result.pending_action_id, result.confirmation_choices,
            )
        return LoopOutcome(result.response, "end_turn")
```

In `_handle_via_skills`, add it to the constructed `AgentResponse`:

```python
            confirmation_choices=result.confirmation_choices,
```

In `apps/vault-server/src/api/routes/message.py`, add `"confirmation_choices": result.confirmation_choices,` to all four response dicts (the non-streaming `/message` return, the streaming `final_payload`, and both `/message/confirm` returns).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/ -q`
Expected: all pass (591+).

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/services/agent_service.py apps/vault-server/src/services/skill_executor.py apps/vault-server/src/api/routes/message.py apps/vault-server/tests/test_skill_loop.py
git commit -m "feat(vault-server): add confirmation_choices to the confirmation contract

The server names the options a confirmation offers; clients render
whatever they are given. Absent (the default) means the existing
free-text yes/no path is unchanged, so every current confirmation keeps
working."
```

---

### Task 3: Render the choices as an inline keyboard

**Files:**
- Modify: `packages/shared-types/src/message.ts`
- Modify: `apps/telegram-bot/src/conversations/message.ts`
- Modify: `apps/telegram-bot/src/callbacks/index.ts`
- Create: `apps/telegram-bot/tests/confirmation-choices.test.ts`

**Interfaces:**
- Consumes: `MessageResponse.confirmation_choices` from Task 2.
- Produces: callback data `confirm:<action_id>:<value>`, posted to `/message/confirm` as `response = <value>`.

- [ ] **Step 1: Write the failing test**

Create `apps/telegram-bot/tests/confirmation-choices.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { buildConfirmationKeyboard } from "../src/keyboards/confirmation.js";

describe("buildConfirmationKeyboard", () => {
  it("renders one button per choice, keyed by action id", () => {
    const kb = buildConfirmationKeyboard("act_1", [
      { value: "autonomous", label: "Autonomous" },
      { value: "handoff", label: "Hand-off" },
    ]);

    const rows = kb.inline_keyboard;
    expect(rows.flat().map((b) => b.text)).toEqual(["Autonomous", "Hand-off"]);
    expect(rows.flat().map((b) => (b as { callback_data: string }).callback_data)).toEqual([
      "confirm:act_1:autonomous",
      "confirm:act_1:handoff",
    ]);
  });

  it("puts each choice on its own row so long labels stay readable", () => {
    const kb = buildConfirmationKeyboard("act_1", [
      { value: "a", label: "Hand-off — checkpoints" },
      { value: "b", label: "Hand-off — run through" },
    ]);

    expect(kb.inline_keyboard.length).toBe(2);
  });

  it("returns no keyboard for an empty choice list", () => {
    const kb = buildConfirmationKeyboard("act_1", []);

    expect(kb.inline_keyboard.flat()).toEqual([]);
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/telegram-bot && npx vitest run tests/confirmation-choices.test.ts`
Expected: FAILS — cannot resolve `../src/keyboards/confirmation.js`.

- [ ] **Step 3: Build the keyboard and wire it up**

Create `apps/telegram-bot/src/keyboards/confirmation.ts`:

```typescript
import { InlineKeyboard } from "grammy";

export interface ConfirmationChoice {
  value: string;
  label: string;
}

/** One button per choice, each on its own row. Callback data carries the
 *  action id so a stale button cannot answer a newer confirmation. */
export function buildConfirmationKeyboard(
  actionId: string,
  choices: ConfirmationChoice[],
): InlineKeyboard {
  const kb = new InlineKeyboard();
  for (const choice of choices) {
    kb.text(choice.label, `confirm:${actionId}:${choice.value}`).row();
  }
  return kb;
}
```

Add to `packages/shared-types/src/message.ts`, inside `MessageResponse`:

```typescript
  confirmation_choices?: { value: string; label: string }[] | null;
```

In `apps/telegram-bot/src/conversations/message.ts`, wherever the agent reply is sent via `sendRich(ctx, { markdown: response.response })`, pass the keyboard when choices are present:

```typescript
        const extra =
          response.awaiting_confirmation && response.pending_action_id && response.confirmation_choices?.length
            ? {
                reply_markup: buildConfirmationKeyboard(
                  response.pending_action_id,
                  response.confirmation_choices,
                ),
              }
            : undefined;
        await sendRich(ctx, { markdown: response.response }, extra);
```

Add the import at the top of the file:

```typescript
import { buildConfirmationKeyboard } from "../keyboards/confirmation.js";
```

In `apps/telegram-bot/src/callbacks/index.ts`, add a handler alongside the existing ones:

```typescript
// Confirmation choice buttons. The action id is embedded in the callback
// data rather than read from module state, so a button from an older
// message cannot answer a newer confirmation.
callbackHandlers.callbackQuery(/^confirm:([^:]+):(.+)$/, async (ctx) => {
  const actionId = ctx.match[1]!;
  const value = ctx.match[2]!;
  try {
    await ctx.answerCallbackQuery();
    const chatId = ctx.chat?.id;
    if (!chatId) return;
    const response = await api.sendConfirmation(chatId, actionId, value);
    await ctx.reply(response.response, { parse_mode: "HTML" });
  } catch (err) {
    markActiveSpanError(err);
    await ctx.answerCallbackQuery({ text: "Something went wrong." });
  }
});
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/telegram-bot && npx vitest run`
Expected: all suites pass, including the 3 new cases.

- [ ] **Step 5: Commit**

```bash
git add packages/shared-types/src/message.ts apps/telegram-bot/src/keyboards/confirmation.ts apps/telegram-bot/src/conversations/message.ts apps/telegram-bot/src/callbacks/index.ts apps/telegram-bot/tests/confirmation-choices.test.ts
git commit -m "feat(bot): render confirmation_choices as an inline keyboard

The bot renders whatever choices the server names and knows nothing about
coding sessions. Callback data embeds the action id so a stale button
cannot answer a newer confirmation."
```

---

### Task 4: Offer the lanes on `propose_coding_session`

**Files:**
- Modify: `apps/vault-server/src/services/tool_handlers/coding_handoff.py`
- Modify: `apps/vault-server/src/services/agent_service.py`
- Modify: `apps/vault-server/tests/test_tool_handlers_coding_handoff.py`

**Interfaces:**
- Produces: `SESSION_CHOICES` — the list offered at the gate.
- Produces: `propose_coding_session(coding_tasks, params, chat_id)` reads `params["session_mode"]`, defaulting to `"handoff-checkpoints"`.

- [ ] **Step 1: Write the failing test**

Append to `apps/vault-server/tests/test_tool_handlers_coding_handoff.py`:

```python
def test_session_choices_cover_every_lane():
    from src.services.tool_handlers.coding_handoff import SESSION_CHOICES

    values = [c["value"] for c in SESSION_CHOICES]
    assert values == [
        "autonomous",
        "handoff-checkpoints",
        "handoff-run-through",
        "handoff-wait",
    ]
    assert all(c["label"] for c in SESSION_CHOICES)


def test_propose_passes_the_chosen_mode_to_launch():
    from unittest.mock import MagicMock
    from src.services.tool_handlers.coding_handoff import propose_coding_session

    coding_tasks = MagicMock()
    coding_tasks.worktrees_path = Path("/tmp/agent-sessions")
    coding_tasks.find_recent_trace_id.return_value = None
    coding_tasks.assemble_brief.return_value = "brief"
    coding_tasks.launch.side_effect = lambda task: {**task, "status": "running", "worktree_path": "/tmp/x"}

    propose_coding_session(
        coding_tasks,
        {"task_description": "fix it", "session_mode": "autonomous"},
        chat_id=42,
    )

    assert coding_tasks.launch.call_args[0][0]["session_mode"] == "autonomous"


def test_propose_defaults_to_handoff_checkpoints():
    from unittest.mock import MagicMock
    from src.services.tool_handlers.coding_handoff import propose_coding_session

    coding_tasks = MagicMock()
    coding_tasks.worktrees_path = Path("/tmp/agent-sessions")
    coding_tasks.find_recent_trace_id.return_value = None
    coding_tasks.assemble_brief.return_value = "brief"
    coding_tasks.launch.side_effect = lambda task: {**task, "status": "running", "worktree_path": "/tmp/x"}

    propose_coding_session(coding_tasks, {"task_description": "fix it"}, chat_id=42)

    assert coding_tasks.launch.call_args[0][0]["session_mode"] == "handoff-checkpoints"
```

Add `from pathlib import Path` to that test file's imports if absent.

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_tool_handlers_coding_handoff.py -v`
Expected: the 3 new tests FAIL — `SESSION_CHOICES` does not exist, and `session_mode` is not in the task dict.

- [ ] **Step 3: Add the choices and the mode**

In `apps/vault-server/src/services/tool_handlers/coding_handoff.py`, add near the top:

```python
# Offered at the confirmation gate. Autonomous exits when done and is
# polled; every hand-off variant stays alive as an interactive Remote
# Control session and is never monitored. The variants differ only in the
# brief's wording -- see the design spec §3.1.
SESSION_CHOICES = [
    {"value": "autonomous", "label": "Autonomous (runs alone, notifies)"},
    {"value": "handoff-checkpoints", "label": "Hand-off — checkpoints"},
    {"value": "handoff-run-through", "label": "Hand-off — run through"},
    {"value": "handoff-wait", "label": "Hand-off — wait for me"},
]

DEFAULT_SESSION_MODE = "handoff-checkpoints"
```

In `propose_coding_session`, set the mode on the task dict before saving:

```python
    session_mode = params.get("session_mode", DEFAULT_SESSION_MODE)
```

and add `"session_mode": session_mode,` to the `task` dict.

In `agent_service.py`'s `propose_coding_session` tool schema, add to `properties`:

```python
                            "session_mode": {
                                "type": "string",
                                "enum": [c["value"] for c in _SESSION_CHOICES],
                                "description": "Chosen at the confirmation gate; do not set this yourself",
                            },
```

Import it alongside the existing handler imports:

```python
from src.services.tool_handlers.coding_handoff import (
    SESSION_CHOICES as _SESSION_CHOICES,
    preview_coding_session as _preview_coding_session,
    propose_coding_session as _propose_coding_session,
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/services/tool_handlers/coding_handoff.py apps/vault-server/src/services/agent_service.py apps/vault-server/tests/test_tool_handlers_coding_handoff.py
git commit -m "feat(vault-server): offer session lanes on propose_coding_session

Four choices: autonomous, and three hand-off variants that differ only in
the brief's wording. Defaults to hand-off checkpoints, which is the lane
that matches how these tasks actually get used today."
```

---

### Task 5: Surface the choices at the gate and inject the answer

**Files:**
- Modify: `apps/vault-server/src/services/agent_service.py`
- Modify: `apps/vault-server/tests/test_agent_service.py`

**Interfaces:**
- Consumes: `SESSION_CHOICES` (Task 4), `AgentResponse.confirmation_choices` (Task 2).
- Produces: a pending `propose_coding_session` call carries `SESSION_CHOICES` out; a matching answer is injected as `params["session_mode"]`.

- [ ] **Step 1: Write the failing test**

Append to `apps/vault-server/tests/test_agent_service.py`:

```python
def test_choice_answer_is_injected_as_session_mode(mock_services):
    """The gate's answer is the lane. Without injection the tool would run
    with its default no matter which button was pressed."""
    from src.services.agent_service import AgentService, PendingAction

    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(
        claude=claude, vault=vault, memory=memory, calendar=calendar, events=events,
    )

    captured = {}
    def fake_execute(name, params, **kwargs):
        captured["params"] = params
        return {"ok": True, "data": {}, "_items": []}
    agent._execute_tool = fake_execute
    agent._run_agent_turn = lambda **kwargs: MagicMock(
        response="done", awaiting_confirmation=False, pending_action_id=None,
        confirmation_choices=None, iterations=1,
    )

    agent.pending_confirmations["act_1"] = PendingAction(
        chat_id=42,
        messages=[],
        assistant_response=MagicMock(content=[]),
        executed_results=[],
        pending_calls=[{
            "id": "tu_1",
            "name": "propose_coding_session",
            "input": {"task_description": "fix it", "_confidence": 0.9},
        }],
        parent_span_context=None,
    )

    agent.handle_confirmation(42, "act_1", "autonomous")

    assert captured["params"]["session_mode"] == "autonomous"


def test_plain_yes_still_confirms_without_a_mode(mock_services):
    from src.services.agent_service import AgentService, PendingAction

    claude, vault, memory, calendar, events = mock_services
    agent = AgentService(
        claude=claude, vault=vault, memory=memory, calendar=calendar, events=events,
    )

    captured = {}
    def fake_execute(name, params, **kwargs):
        captured["params"] = params
        return {"ok": True, "data": {}, "_items": []}
    agent._execute_tool = fake_execute
    agent._run_agent_turn = lambda **kwargs: MagicMock(
        response="done", awaiting_confirmation=False, pending_action_id=None,
        confirmation_choices=None, iterations=1,
    )

    agent.pending_confirmations["act_2"] = PendingAction(
        chat_id=42,
        messages=[],
        assistant_response=MagicMock(content=[]),
        executed_results=[],
        pending_calls=[{
            "id": "tu_2",
            "name": "delete_task",
            "input": {"name": "old task", "_confidence": 0.99},
        }],
        parent_span_context=None,
    )

    agent.handle_confirmation(42, "act_2", "yes")

    assert "session_mode" not in captured["params"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_agent_service.py -k session_mode -v`
Expected: `test_choice_answer_is_injected_as_session_mode` FAILS with `KeyError: 'session_mode'`.

- [ ] **Step 3: Attach choices and accept them as affirmative**

In `agent_service.py`, add a module-level helper above `AgentService`:

```python
_CHOICE_VALUES = {c["value"] for c in _SESSION_CHOICES}
_AFFIRMATIVE = ("yes", "y", "ok", "sure", "do it")


def _choices_for(calls: list[dict]) -> list[dict] | None:
    """Choices a pending batch offers, or None for a plain yes/no gate."""
    if any(c["name"] == "propose_coding_session" for c in calls):
        return _SESSION_CHOICES
    return None
```

In `_run_agent_turn`'s confirmation branch, pass them out with the response:

```python
                            return AgentResponse(
                                response=description,
                                awaiting_confirmation=True,
                                pending_action_id=pending_action_id,
                                confirmation_choices=_choices_for(needs_confirmation),
                            )
```

In `_handle_confirmation_inner`, replace the affirmative check and inject the mode:

```python
            answer = user_response.lower().strip()
            chosen_mode = answer if answer in _CHOICE_VALUES else None
            if answer in _AFFIRMATIVE or chosen_mode:
                tool_results = list(pending.executed_results)
                pre_tools_audit: list[dict] = []
                for call in pending.pending_calls:
                    params = dict(call["input"])
                    # The gate's answer *is* the lane. Without this the tool
                    # would run with its default whichever button was pressed.
                    if chosen_mode and call["name"] == "propose_coding_session":
                        params["session_mode"] = chosen_mode
```

Leave the rest of the branch unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/services/agent_service.py apps/vault-server/tests/test_agent_service.py
git commit -m "feat(vault-server): surface lane choices at the gate and inject the answer

A pending propose_coding_session carries its choices out to the client,
and a matching answer is injected as session_mode before execution --
otherwise the tool would run with its default whichever button was
pressed. Plain yes/no is untouched for every other confirmation."
```

---

### Task 6: Write briefs that match the lane

The current brief says "Do not push to master/origin directly", which a real session read as *do not push at all* — it committed locally and reported "not pushed anywhere, per the constraints", leaving work inside a disposable clone.

**Files:**
- Modify: `apps/vault-server/src/services/coding_tasks_service.py`
- Modify: `apps/vault-server/tests/test_coding_tasks_service.py`

**Interfaces:**
- Produces: `assemble_brief(..., session_mode: str)` — appends a lane-specific closing instruction.

- [ ] **Step 1: Write the failing test**

Append to `apps/vault-server/tests/test_coding_tasks_service.py`, inside the class that already tests `assemble_brief` (or as module-level functions if there is none):

```python
class TestBriefPerLane:
    def _brief(self, service, mode):
        return service.assemble_brief(
            task_description="fix the thing",
            conversation_excerpt="it is broken",
            likely_area="apps/vault-server",
            branch="coding-agent/ct_1",
            worktree_path=Path("/workspace"),
            test_command="npx turbo test",
            trace_id=None,
            reported_at=datetime(2026, 8, 8, tzinfo=timezone.utc),
            session_mode=mode,
        )

    def test_autonomous_brief_mandates_push_and_pr(self, service):
        """A clone is its own object database: work committed and never
        pushed exists in exactly one place, and that place is disposable."""
        brief = self._brief(service, "autonomous")

        assert "git push -u origin" in brief
        assert "gh pr create" in brief
        assert "do not push at all" not in brief.lower()

    def test_checkpoints_brief_asks_the_session_to_stop_and_wait(self, service):
        brief = self._brief(service, "handoff-checkpoints")

        assert "check in" in brief.lower()
        assert "gh pr create" not in brief

    def test_run_through_brief_asks_for_completion_then_a_report(self, service):
        brief = self._brief(service, "handoff-run-through")

        assert "run to completion" in brief.lower()

    def test_wait_brief_tells_the_session_to_do_nothing_yet(self, service):
        brief = self._brief(service, "handoff-wait")

        assert "wait" in brief.lower()
        assert "do not start" in brief.lower()

    def test_every_brief_points_at_the_conventions(self, service):
        """CONVENTIONS.md ships in every clone but nothing autoloads it."""
        for mode in ("autonomous", "handoff-checkpoints", "handoff-run-through", "handoff-wait"):
            assert "infra/coding-agent/CONVENTIONS.md" in self._brief(service, mode)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_coding_tasks_service.py -k Brief -v`
Expected: FAILS with `TypeError: assemble_brief() got an unexpected keyword argument 'session_mode'`.

- [ ] **Step 3: Make the brief lane-aware**

In `coding_tasks_service.py`, add above the class:

```python
# The closing instruction is the only thing that differs between lanes.
# Autonomous exits when done, so "done" has to mean the work is durable:
# a clone is its own object database, and anything committed but never
# pushed exists in exactly one place, which is disposable.
_LANE_INSTRUCTIONS = {
    "autonomous": (
        "- When the work is done: commit, `git push -u origin {branch}`, then "
        "`gh pr create`. The upstream is mandatory. Do this separately for "
        "/workspace and /workspace/memory if you touched both.\n"
        "- Do not push to master. It is branch-protected; open a PR.\n"
    ),
    "handoff-checkpoints": (
        "- Work in steps and stop to check in at each natural checkpoint. A "
        "human will join this session to steer it.\n"
        "- Do not push to master. Leave landing decisions to the human.\n"
    ),
    "handoff-run-through": (
        "- Run to completion, then report what you did and wait. A human will "
        "join this session to review.\n"
        "- Do not push to master. Leave landing decisions to the human.\n"
    ),
    "handoff-wait": (
        "- Do not start yet. Read the task above and wait for instructions; a "
        "human will join this session and drive it.\n"
    ),
}
```

Change the signature to accept `session_mode: str = "handoff-checkpoints"` and replace the working-constraints block:

```python
        lane = _LANE_INSTRUCTIONS.get(session_mode, _LANE_INSTRUCTIONS["handoff-checkpoints"])
        return (
            "You're picking up a task reported via Mazkir's Telegram bot.\n\n"
            "## Task\n"
            f"{task_description}\n\n"
            "## Context\n"
            f"- Reported: {reported_at.isoformat(timespec='minutes')}, trace_id: {trace_line}\n"
            f"- Likely area: {likely_area}\n"
            "- Conversation excerpt:\n"
            f"  > {conversation_excerpt}\n\n"
            "## Working constraints\n"
            f"- Worktree at {worktree_path}, branch {branch}. Do not touch anything outside it.\n"
            f"- Run `{test_command}` before considering this done.\n"
            f"{lane.format(branch=branch)}"
            "- Summarize what changed and why in your final message.\n\n"
            "Read `infra/coding-agent/CONVENTIONS.md` first — it covers the two-repo\n"
            "layout, why `memory/` may be empty, and why you must never guess at\n"
            "absolute host paths. See CLAUDE.md for the architecture map.\n"
        )
```

Pass the mode through from `tool_handlers/coding_handoff.py`'s `assemble_brief` call:

```python
        session_mode=session_mode,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/services/coding_tasks_service.py apps/vault-server/src/services/tool_handlers/coding_handoff.py apps/vault-server/tests/test_coding_tasks_service.py
git commit -m "feat(vault-server): write briefs that match the chosen lane

The old brief said 'do not push to master/origin directly', which a real
session read as do-not-push-at-all: it committed locally and reported
'not pushed anywhere, per the constraints'. A clone is its own object
database, so that work existed in exactly one disposable place.

Autonomous briefs now mandate commit, push -u, and a PR. Hand-off briefs
tell the session a human is joining. Every brief points at CONVENTIONS.md,
which ships in the clone but nothing autoloads."
```

---

### Task 7: Route `spawn_container` through `session.sh`

**Files:**
- Modify: `apps/vault-server/src/config.py`
- Modify: `apps/vault-server/src/services/coding_tasks_service.py`
- Modify: `apps/vault-server/src/main.py`
- Modify: `apps/vault-server/tests/test_coding_tasks_service.py`

**Interfaces:**
- Produces: `CodingTasksService(session_script=Path, ...)`; `launch(task)` invokes `session.sh start <id> --mode=<lane> --prompt-file=<path> --root=<sessions_root>`.

- [ ] **Step 1: Write the failing test**

Append to `apps/vault-server/tests/test_coding_tasks_service.py`:

```python
class TestLaunchViaSessionScript:
    def _service(self, tmp_path):
        return CodingTasksService(
            data_path=tmp_path / "coding-tasks",
            repo_path=tmp_path / "repo",
            worktrees_path=tmp_path / "agent-sessions",
            docker_image="mazkir-coding-agent:test",
            notifier=TelegramNotifier(bot_token=None),
            session_script=tmp_path / "session.sh",
        )

    def test_launch_shells_out_to_session_script(self, tmp_path):
        """One implementation for automated and manual paths. They drifted
        before: docker-compose.yml mounted ~/.claude.json and
        spawn_container did not, which broke every automated session."""
        service = self._service(tmp_path)
        task = {
            "id": "ct_1", "chat_id": 42, "branch": "coding-agent/ct_1",
            "prompt": "fix the bug", "status": "proposed",
            "task_description": "fix the bug", "session_mode": "autonomous",
        }

        with patch("src.services.coding_tasks_service.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", returncode=0)
            service.launch(task)

        args = mock_run.call_args[0][0]
        assert args[0] == str(tmp_path / "session.sh")
        assert args[1] == "start"
        assert "ct_1" in args
        assert "--mode=autonomous" in args
        assert f"--root={tmp_path / 'agent-sessions'}" in args

    def test_launch_maps_handoff_variants_to_the_handoff_mode(self, tmp_path):
        """session.sh knows three modes; the variants differ only in the
        brief, which is already baked into the prompt file."""
        service = self._service(tmp_path)
        task = {
            "id": "ct_2", "chat_id": 42, "branch": "coding-agent/ct_2",
            "prompt": "fix it", "status": "proposed",
            "task_description": "fix it", "session_mode": "handoff-run-through",
        }

        with patch("src.services.coding_tasks_service.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", returncode=0)
            service.launch(task)

        assert "--mode=handoff" in mock_run.call_args[0][0]

    def test_launch_writes_the_brief_to_the_prompt_file_it_passes(self, tmp_path):
        service = self._service(tmp_path)
        task = {
            "id": "ct_3", "chat_id": 42, "branch": "coding-agent/ct_3",
            "prompt": "the actual brief text", "status": "proposed",
            "task_description": "x", "session_mode": "autonomous",
        }

        with patch("src.services.coding_tasks_service.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", returncode=0)
            service.launch(task)

        args = mock_run.call_args[0][0]
        prompt_arg = next(a for a in args if a.startswith("--prompt-file="))
        assert Path(prompt_arg.split("=", 1)[1]).read_text() == "the actual brief text"

    def test_launch_marks_failed_when_the_script_fails(self, tmp_path):
        service = self._service(tmp_path)
        task = {
            "id": "ct_4", "chat_id": 42, "branch": "coding-agent/ct_4",
            "prompt": "fix it", "status": "proposed",
            "task_description": "fix it", "session_mode": "autonomous",
        }

        with patch("src.services.coding_tasks_service.subprocess.run",
                   side_effect=subprocess.CalledProcessError(1, "session.sh", stderr="boom")):
            with patch.object(service.notifier, "send_message") as mock_notify:
                launched = service.launch(task)

        assert launched["status"] == "failed"
        assert service.get_task("ct_4")["status"] == "failed"
        mock_notify.assert_called_once()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_coding_tasks_service.py -k SessionScript -v`
Expected: FAILS — `CodingTasksService.__init__() got an unexpected keyword argument 'session_script'`.

- [ ] **Step 3: Replace the provisioning path**

In `config.py`, replace the `coding_agent_worktrees_path` default and add the script path:

```python
    coding_agent_worktrees_path: Path = Path(os.getenv(
        "AGENT_SESSIONS_ROOT",
        str(Path.home() / "dev" / "agent-sessions"),
    ))
    coding_agent_session_script: Path = Path(os.getenv(
        "CODING_AGENT_SESSION_SCRIPT",
        str(Path.home() / "dev" / "mazkir" / "infra" / "coding-agent" / "session.sh"),
    ))
```

In `coding_tasks_service.py`, accept `session_script: Path | None = None` in `__init__` and store it. Replace `launch` with:

```python
    # session.sh owns provisioning and launching for every lane. Building a
    # second docker invocation here is what let the automated and manual
    # paths drift apart: docker-compose.yml mounted ~/.claude.json and
    # spawn_container did not, and every automated session died on boot.
    _MODE_MAP = {
        "autonomous": "autonomous",
        "handoff-checkpoints": "handoff",
        "handoff-run-through": "handoff",
        "handoff-wait": "manual",
    }

    def launch(self, task: dict[str, Any]) -> dict[str, Any]:
        """Provision and start a session via session.sh, persisting state.

        Returns the task rather than raising, so callers that build a normal
        'ok' response from it (propose_coding_session) need no special
        casing -- they just see status == 'failed'.
        """
        session_mode = task.get("session_mode", "handoff-checkpoints")
        mode = self._MODE_MAP.get(session_mode, "handoff")

        prompt_path = self.data_path / f"{task['id']}-prompt.md"
        prompt_path.write_text(task["prompt"])

        cmd = [
            str(self.session_script), "start", task["id"],
            f"--mode={mode}",
            f"--root={self.worktrees_path}",
        ]
        if mode != "manual":
            cmd.append(f"--prompt-file={prompt_path}")

        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except Exception as e:
            logger.error(f"session.sh failed for task {task['id']}: {e}")
            task["status"] = "failed"
            task["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            task["summary"] = f"Failed to launch coding session: {e}"
            task["worktree_path"] = str(self.worktrees_path / task["id"])
            self.save_task(task)
            self.notifier.send_message(
                task.get("chat_id"),
                f"Coding session FAILED: {task.get('task_description', '?')}\n\n"
                f"Branch: {task['branch']}\n\n{task['summary'][-500:]}",
            )
            return task

        task["worktree_path"] = str(self.worktrees_path / task["id"])
        task["status"] = "running"
        task["started_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.save_task(task)
        return task
```

Delete `spawn_container`, `_clone_repo`, `create_worktree`, `create_vault_worktree`, `_remove_worktree`, and `_git_credential_env_file` — `session.sh` owns all of it now. Remove the tests covering those methods in the same commit.

In `main.py`, pass the new setting:

```python
        session_script=settings.coding_agent_session_script,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/config.py apps/vault-server/src/services/coding_tasks_service.py apps/vault-server/src/main.py apps/vault-server/tests/test_coding_tasks_service.py
git commit -m "refactor(vault-server): launch sessions through session.sh

spawn_container built its own docker run arguments, a second definition
of the same container. They drifted: docker-compose.yml mounted
~/.claude.json and spawn_container did not, so every automated session
booted on an empty config and exited within 14 seconds.

Provisioning, credentials, and launching now live only in session.sh.
Sessions move to ~/dev/agent-sessions to match it."
```

---

### Task 8: Hand-off sessions are not monitored

**Files:**
- Modify: `apps/vault-server/src/services/coding_tasks_service.py`
- Modify: `apps/vault-server/tests/test_coding_tasks_service.py`

**Interfaces:**
- Produces: `check_running_tasks()` skips any task whose `session_mode` is not `autonomous`.

- [ ] **Step 1: Write the failing test**

Append to `apps/vault-server/tests/test_coding_tasks_service.py`:

```python
class TestHandoffIsUnmonitored:
    def test_poller_ignores_handoff_sessions(self, service):
        """A hand-off session stays alive by design. Polling it would
        transition it the moment the user closed the container."""
        service.save_task({
            "id": "ct_h", "chat_id": 42, "status": "running",
            "session_mode": "handoff-checkpoints", "container_id": "c1",
            "task_description": "fix it", "branch": "coding-agent/ct_h",
            "worktree_path": "/tmp/w",
        })

        with patch("src.services.coding_tasks_service.subprocess.run") as mock_run:
            transitioned = service.check_running_tasks()

        assert transitioned == []
        assert mock_run.call_count == 0, "must not shell out for hand-off sessions"
        assert service.get_task("ct_h")["status"] == "running"

    def test_poller_still_handles_autonomous_sessions(self, service):
        service.save_task({
            "id": "ct_a", "chat_id": 42, "status": "running",
            "session_mode": "autonomous", "container_id": "c2",
            "task_description": "fix it", "branch": "coding-agent/ct_a",
            "worktree_path": "/tmp/w",
        })

        with patch("src.services.coding_tasks_service.subprocess.run",
                   side_effect=TestCheckRunningTasks._exited_container()):
            with patch.object(service.notifier, "send_message"):
                transitioned = service.check_running_tasks()

        assert len(transitioned) == 1
        assert service.get_task("ct_a")["status"] == "done"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_coding_tasks_service.py -k Unmonitored -v`
Expected: `test_poller_ignores_handoff_sessions` FAILS — the poller shells out for every running task.

- [ ] **Step 3: Skip non-autonomous tasks**

In `check_running_tasks`, add immediately inside the loop:

```python
        for task in self.list_tasks(status="running"):
            # Hand-off and manual sessions stay alive by design and are never
            # monitored: there is no completion to detect, and polling would
            # transition them the moment the user closed the container.
            if task.get("session_mode", "handoff-checkpoints") != "autonomous":
                continue
```

Note the container id for autonomous tasks now comes from `docker ps` by name rather than from `launch`, since `session.sh` owns the container. Resolve it once at the top of the loop body:

```python
            container_id = task.get("container_id") or f"mazkir-coding-{task['id']}"
```

and use `container_id` in place of `task["container_id"]` throughout the body.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/services/coding_tasks_service.py apps/vault-server/tests/test_coding_tasks_service.py
git commit -m "feat(vault-server): leave hand-off sessions unmonitored

A hand-off session stays alive by design -- there is no exit to detect,
and polling would transition it the moment the user closed the container.
Only autonomous tasks are polled, notified, and cleaned."
```

---

### Task 9: Autonomous cleanup delegates to `session.sh clean`

**Files:**
- Modify: `apps/vault-server/src/services/coding_tasks_service.py`
- Modify: `apps/vault-server/tests/test_coding_tasks_service.py`

**Interfaces:**
- Produces: after a terminal transition, `check_running_tasks` invokes `session.sh clean <id> --root=<sessions_root>` and records the outcome on the task.

- [ ] **Step 1: Write the failing test**

Append to `apps/vault-server/tests/test_coding_tasks_service.py`:

```python
class TestAutonomousCleanup:
    def _autonomous_task(self, service, task_id="ct_c"):
        service.save_task({
            "id": task_id, "chat_id": 42, "status": "running",
            "session_mode": "autonomous", "container_id": "c1",
            "task_description": "fix it", "branch": f"coding-agent/{task_id}",
            "worktree_path": "/tmp/w",
        })

    def test_cleanup_calls_session_script_after_a_terminal_transition(self, service):
        """One implementation of 'is this safe to delete' -- reimplementing
        rmtree here would be a second place to be wrong about unpushed work."""
        self._autonomous_task(service)
        exited = TestCheckRunningTasks._exited_container()
        calls = []

        def record(args, **kwargs):
            calls.append(args)
            if args and str(args[0]).endswith("session.sh"):
                return MagicMock(stdout="removed", returncode=0)
            return exited(args, **kwargs)

        with patch("src.services.coding_tasks_service.subprocess.run", side_effect=record):
            with patch.object(service.notifier, "send_message"):
                service.check_running_tasks()

        assert any(
            str(a[0]).endswith("session.sh") and a[1] == "clean" for a in calls
        ), "expected a session.sh clean invocation"

    def test_a_refused_cleanup_leaves_the_task_done_and_records_why(self, service):
        """clean refuses while work is unpushed. That is not a task failure."""
        self._autonomous_task(service, "ct_keep")
        exited = TestCheckRunningTasks._exited_container()

        def refuse(args, **kwargs):
            if args and str(args[0]).endswith("session.sh"):
                raise subprocess.CalledProcessError(
                    1, args, stderr="refusing to remove ct_keep: workspace has unpushed commits",
                )
            return exited(args, **kwargs)

        with patch("src.services.coding_tasks_service.subprocess.run", side_effect=refuse):
            with patch.object(service.notifier, "send_message"):
                service.check_running_tasks()

        saved = service.get_task("ct_keep")
        assert saved["status"] == "done"
        assert "unpushed" in saved.get("cleanup_note", "")
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_coding_tasks_service.py -k AutonomousCleanup -v`
Expected: both FAIL — no `session.sh clean` call, no `cleanup_note`.

- [ ] **Step 3: Delegate cleanup**

Add to `coding_tasks_service.py`:

```python
    def _clean_session(self, task_id: str) -> str | None:
        """Ask session.sh whether this session is safe to remove, and remove
        it if so. The four predicates live there and only there -- a second
        implementation here would be a second place to be wrong about
        destroying unpushed work. A refusal is expected, not a failure.
        Returns the refusal reason, or None when the session was removed."""
        try:
            subprocess.run(
                [str(self.session_script), "clean", task_id, f"--root={self.worktrees_path}"],
                check=True, capture_output=True, text=True,
            )
            return None
        except subprocess.CalledProcessError as e:
            note = (e.stderr or "").strip() or "cleanup refused"
            logger.info(f"session {task_id} kept: {note}")
            return note
        except Exception as e:
            logger.warning(f"cleanup failed for session {task_id}: {e}")
            return str(e)
```

In `check_running_tasks`, after `self.save_task(task)` and container removal, before notifying:

```python
            note = self._clean_session(task["id"])
            if note:
                task["cleanup_note"] = note
                self.save_task(task)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/vault-server && source venv/bin/activate && python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/vault-server/src/services/coding_tasks_service.py apps/vault-server/tests/test_coding_tasks_service.py
git commit -m "feat(vault-server): delegate autonomous cleanup to session.sh clean

The four retention predicates live in session.sh and only there. A
refusal (unpushed work) is recorded as a cleanup_note and leaves the task
done -- it is the expected outcome for a session that did not push, not a
failure."
```

---

### Task 10: Doppler, and reconcile the drifted CLAUDE.md

**Files:**
- Modify: `infra/coding-agent/Dockerfile`
- Modify: `infra/coding-agent/session.sh`
- Modify: `infra/coding-agent/SETUP.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add the Doppler CLI to the image**

In `infra/coding-agent/Dockerfile`, after the `uv` block:

```dockerfile
# Doppler: sessions fetch configuration at runtime rather than carrying a
# .env of secrets in the clone. The token arrives via the credential
# env-file at launch, never in argv.
RUN curl -fsSL https://cli.doppler.com/install.sh | sh
```

- [ ] **Step 2: Pass a Doppler token through the credential file**

In `session.sh`'s `write_credential_env_file`, after the GitHub block, add:

```bash
  if [ -n "${DOPPLER_TOKEN:-}" ]; then
    echo "DOPPLER_TOKEN=${DOPPLER_TOKEN}" >> "$out"
  fi
```

Note the function currently writes with `>` inside a block; change that block to append-safe form by initializing the file first:

```bash
  : > "$out"
  if [ -n "$token" ]; then
    {
      echo "GIT_CONFIG_COUNT=1"
      echo "GIT_CONFIG_KEY_0=url.https://x-access-token:${token}@github.com/.insteadOf"
      echo "GIT_CONFIG_VALUE_0=git@github.com:"
      echo "GH_TOKEN=${token}"
    } >> "$out"
  fi
```

- [ ] **Step 3: Verify the image and script still work**

```bash
docker build -t mazkir-coding-agent:latest infra/coding-agent/
docker run --rm mazkir-coding-agent:latest doppler --version
./infra/coding-agent/smoke-test.sh
cd apps/vault-server && source venv/bin/activate && python -m pytest tests/test_session_script.py -q
```

Expected: a Doppler version string, `SMOKE TEST PASSED`, and all session-script tests passing.

- [ ] **Step 4: Document Doppler and fix CLAUDE.md's drift**

Add to `infra/coding-agent/SETUP.md` after the GitHub PAT section:

```markdown
## Secrets via Doppler

Sessions fetch configuration at runtime instead of carrying secrets in the
clone. Export `DOPPLER_TOKEN` before launching and `session.sh` passes it
through the credential env-file (never argv):

    export DOPPLER_TOKEN=dp.st....
    ./infra/coding-agent/session.sh start my-task

Inside a session, `doppler run -- <command>` injects the configured values.

**Currently sessions share your real credentials.** A separate test-scoped
project is deliberately deferred. What still holds: the live vault is never
mounted (sessions get a clone of `mazkir-memory`, so vault changes need
push + PR to land), `master` keeps branch protection, and there is no
`docker.sock`. What is given up: a misbehaving session can spend Anthropic
quota, send Telegram messages as the bot, and push wherever the PAT
reaches. Revisit when sessions run unwatched or more than one at a time.
```

In `CLAUDE.md`, correct the drifted facts — the tool count is stated as 32 and the skill roster as four, both now wrong — and add a coding-sessions entry:

```markdown
- **Coding sessions:** `propose_coding_session` (write tier, always confirmed) offers four lanes at the gate: `autonomous` (headless `claude -p`, polled for exit, notified, worktree auto-cleaned when the four predicates pass) and three hand-off variants (interactive `--remote-control`, attachable from Claude Mobile, never monitored or auto-cleaned). All lanes go through `infra/coding-agent/session.sh`; `CodingTasksService` shells out to it rather than building its own docker invocation. Sessions live in `~/dev/agent-sessions/<id>/` on branch `coding-agent/<id>`.
```

Update the skill roster line to five skills (`mazkir`, `time-management`, `knowledge-management`, `motivation-management`, `engineering`) and the tool count to 33.

- [ ] **Step 5: Commit**

```bash
git add infra/coding-agent/Dockerfile infra/coding-agent/session.sh infra/coding-agent/SETUP.md CLAUDE.md
git commit -m "feat(coding-agent): add Doppler; reconcile CLAUDE.md with reality

Sessions fetch configuration at runtime rather than carrying secrets in
the clone; the token rides the credential env-file, never argv. A
separate test-scoped project is deliberately deferred, and the residual
exposure is documented.

CLAUDE.md still described 32 tools and four skills, and had no
coding-session section at all."
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §3 two lanes, monitored vs not | 7, 8 |
| §3.1 hand-off variants | 4, 6 |
| §5 naming (`<name>` in three places) | 7 |
| §7 cleanup via the predicates | 9 |
| §8 `confirmation_choices`, inline keyboard | 2, 3, 4, 5 |
| §10 Doppler, deferred test scope | 10 |
| §11.4 `sendRich` dropping `extra` | 1 |
| §11.6 brief mandates push | 6 |
| §11.8 CONVENTIONS.md reachable from the brief | 6 |
| §14 documentation | 10 |

**Carried from plan 1 (already done):** §6 provisioning and GitHub origin, §7 predicates, §9.1 no docker.sock, §9.2 Python toolchain and session `.env`, §11.2 local-path origin, §11.3 PAT out of argv, §11.5 host-path defaults, §11.7 worktree root, §13 smoke test.

**Placeholder scan:** none — every step carries runnable code or an exact command.

**Type consistency:** `confirmation_choices` is `list[dict] | None` server-side and `{value,label}[] | null` in shared types, threaded identically through `LoopOutcome`, `SkillExecutorResult`, and `AgentResponse`. `SESSION_CHOICES` values (`autonomous`, `handoff-checkpoints`, `handoff-run-through`, `handoff-wait`) match `_LANE_INSTRUCTIONS` keys in Task 6 and `_MODE_MAP` keys in Task 7. `session_script` is the constructor parameter name in Tasks 7 and 9; `buildConfirmationKeyboard(actionId, choices)` matches its single call site.

**One risk worth naming:** Task 7 deletes `spawn_container`, `create_worktree`, `create_vault_worktree`, and their tests. That is a large deletion in one task, but splitting it would leave two live provisioning implementations mid-plan — exactly the drift this work exists to remove.
