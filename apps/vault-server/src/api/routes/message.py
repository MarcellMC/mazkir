"""Natural language message endpoint — agent loop."""

import asyncio
import datetime
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.auth import verify_api_key
from src.config import settings
from src.services.tracing_helpers import set_payload_provenance

logger = logging.getLogger(__name__)

router = APIRouter(tags=["message"], dependencies=[Depends(verify_api_key)])


class AttachmentModel(BaseModel):
    type: str  # "photo" | "location"
    # Photo fields
    data: str | None = None
    mime_type: str | None = None
    filename: str | None = None
    telegram_date: str | None = None  # Fallback timestamp when EXIF is stripped
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
    selected_date: str | None = None
    attachments: list[AttachmentModel] | None = None
    reply_to: ReplyContextModel | None = None
    forwarded_from: ForwardContextModel | None = None
    # Telegram's own id: a repeat within 10 minutes is answered from the first
    # turn instead of being acted on twice (fast-lane spec §10).
    message_id: int | None = None


class ConfirmationRequest(BaseModel):
    chat_id: int
    action_id: str
    response: str


def _prepare_agent_kwargs(body: MessageRequest) -> dict:
    """Convert MessageRequest Pydantic models to plain dicts for AgentService."""
    attachments = None
    if body.attachments:
        attachments = [a.model_dump(by_alias=True, exclude_none=True) for a in body.attachments]

    reply_to = None
    if body.reply_to:
        reply_to = body.reply_to.model_dump(by_alias=True)

    forwarded_from = None
    if body.forwarded_from:
        forwarded_from = body.forwarded_from.model_dump(exclude_none=True)

    return {
        "text": body.text,
        "chat_id": body.chat_id,
        "selected_date": body.selected_date,
        "attachments": attachments,
        "reply_to": reply_to,
        "forwarded_from": forwarded_from,
    }


def get_agent():
    """Module-level shim — delegates to src.main.get_agent.

    Defined here so tests can patch ``src.api.routes.message.get_agent``
    without importing src.main (which triggers full app initialisation).
    """
    from src.main import get_agent as _get_agent
    return _get_agent()


def get_fast_lane_deps():
    """Module-level shim so tests can patch the services without importing src.main."""
    from src.main import get_claude, get_events, get_memory, get_vault
    return get_claude(), get_memory(), get_events(), get_vault()


_shadow_tasks: set = set()


def _start_fast_lane_shadow(body: MessageRequest):
    """Snapshot the day now, before the agent writes, then parse and resolve in the background.

    Fast-lane spec §11.3: the shadow writes nothing and the reply never waits
    for it. Only the cheap, changeable state is read here, on the event loop;
    a month of past durations and the habit list are read in the shadow's
    thread (`complete_fast_context`). Any failure here is logged and forgotten.
    """
    if settings.fast_lane_mode not in ("shadow", "on"):
        return None
    try:
        from functools import partial
        from zoneinfo import ZoneInfo

        from src.services.fast_lane.context import (
            assemble_fast_context,
            complete_fast_context,
        )
        from src.services.fast_lane.shadow import ShadowSettings, run_shadow

        claude, memory, events, vault = get_fast_lane_deps()
        if claude is None:
            return None
        kwargs = _prepare_agent_kwargs(body)
        ctx = assemble_fast_context(
            text=body.text, chat_id=body.chat_id,
            now=datetime.datetime.now(ZoneInfo(settings.vault_timezone)),
            memory=memory, events=events, vault=vault,
            reply_to=kwargs["reply_to"], selected_date=body.selected_date,
            attachments=kwargs["attachments"],
            places_path=settings.events_data_path.parent / "places.json",
            day_boundary_hour=settings.fast_lane_day_boundary_hour,
        )
        shadow_settings = ShadowSettings(
            model=settings.fast_parse_model, timeout_s=settings.fast_parse_timeout_s,
            day_boundary_hour=settings.fast_lane_day_boundary_hour,
            default_minutes=settings.default_event_duration,
        )
        complete = partial(complete_fast_context, events=events, vault=vault,
                           skills_dir=settings.skills_dir)
    except Exception:
        logger.warning("fast lane shadow could not start", exc_info=True)
        return None
    task = asyncio.create_task(asyncio.to_thread(run_shadow, ctx, claude, shadow_settings, complete=complete))
    _shadow_tasks.add(task)   # keep a reference until it finishes
    task.add_done_callback(_shadow_tasks.discard)
    return task


def get_fast_turn_deps(agent):
    """Module-level shim so tests can patch the services without importing src.main."""
    from src.main import get_calendar, get_claude, get_events, get_memory, get_vault
    from src.services.fast_lane.turn import FastDeps
    data = settings.events_data_path.parent
    deps = FastDeps(claude=get_claude(), run_tool=agent.run_tool, events=get_events(), vault=get_vault(),
                    memory=get_memory(), actions_dir=data / "actions", places_path=data / "places.json",
                    suggestions_path=data / "fast-lane-suggestions.json",
                    # Without it the parse runs with no skill catalog to pick a fallthrough skill from.
                    skills_dir=settings.skills_dir)
    return deps, get_calendar()


def _previous_skill(chat_id: int, date: str) -> str | None:
    """The skill that handled this chat's last turn today, unless the fast lane answered it.

    A mixed turn logs its fast-lane record first and the skill's after it, so
    the last record is the skill's. A pure fast turn's record is last, and a
    lone answer after it is not "right after a skill turn" (spec §5.5).
    """
    from src.services.turn_trace import read_turn_records
    try:
        records = read_turn_records(settings.logs_dir, chat_id, date)
    except Exception:
        logger.warning("could not read the previous turn's skill", exc_info=True)
        return None
    skill = records[-1].get("skill") if records else None
    return skill if skill not in (None, "fast-lane") else None


SYNC_CAP_S = 15.0
STILL_WORKING = "Still working on your previous message."
AGENT_FAILED = "That message failed; please send it again."


# Work that outlives its request: the syncs past the response's cap, and the
# SSE turn whose client disconnected. Held here until done, so nothing drops
# the only reference to a running task.
_fast_tasks: set = set()


def _hold(task: asyncio.Task) -> asyncio.Task:
    _fast_tasks.add(task)
    task.add_done_callback(_fast_tasks.discard)
    return task


def _patch_turn(actions_dir, turn: dict, change) -> dict:
    """Apply `change` to the saved turn under `act.update_turn`'s lock, and return it.

    Undo (and the receipt buttons) rewrite the saved record while syncs and
    the agent are still running here; writing back the copy this route holds,
    or one read before their save, would erase their `undone`/`restored`
    markers. The in-memory copy is saved only when the saved one is gone.
    """
    from src.services.fast_lane import act
    return act.update_turn(actions_dir, turn["turn_id"], change, default=turn)


async def _settle_syncs(turn: dict, deps, calendar, now, emit) -> None:
    """Google after the receipt (spec §7.5): each deferred line syncs, then its receipt line updates.

    A failure is a ⚠ on that line, never the turn's: the block stays in Mazkir
    and its undo record is untouched.
    """
    from src.services import calendar_push
    from src.services.fast_lane.receipt import render_receipt
    for line in turn["lines"]:
        if (line.get("calendar_sync") or {}).get("reason") != "deferred" or not line.get("event_id"):
            continue
        try:
            sync = await asyncio.to_thread(
                calendar_push.sync_block, calendar, deps.events, line["date"], line["event_id"])
        except Exception as e:
            logger.warning("fast lane calendar sync failed for %s", line.get("event_id"), exc_info=True)
            sync = {"ok": False, "attempted": True, "reason": f"sync failed: {e}"}
        line["calendar_sync"] = sync
        line_id = line["id"]

        def change(saved: dict, line_id=line_id, sync=sync) -> None:
            for saved_line in saved["lines"]:
                if saved_line.get("id") == line_id:
                    saved_line["calendar_sync"] = sync

        try:
            saved = await asyncio.to_thread(_patch_turn, deps.actions_dir, turn, change)
        except Exception:
            logger.error("fast lane could not record a calendar sync on turn %s", turn.get("turn_id"),
                         exc_info=True)
            continue
        try:
            # After the response's cap the stream is gone and this goes nowhere.
            emit({"receipt_update": {"line_id": line_id, "receipt": render_receipt(saved, now)}})
        except Exception:
            logger.warning("fast lane could not send a receipt update", exc_info=True)


def _on_reply(*, response: str, route: str, receipt: dict | None, result=None) -> dict:
    return {
        "response": response,
        "awaiting_confirmation": bool(result and result.awaiting_confirmation),
        "pending_action_id": result.pending_action_id if result else None,
        "confirmation_choices": result.confirmation_choices if result else None,
        "receipt": receipt,
        "route": route,
    }


async def _on_turn(body: MessageRequest, agent, *, stream: bool, emit) -> dict:
    """One message with the fast lane on (spec §3.1, §5.5). `emit` sends an SSE payload.

    A pending yes/no never arrives here: the bot sends it to /message/confirm
    (spec §3.1 step 2, unchanged).
    """
    from zoneinfo import ZoneInfo

    from src.services.fast_lane import act
    from src.services.fast_lane import context as context_module
    from src.services.fast_lane import turn as turn_module
    from src.services.fast_lane.receipt import render_receipt
    from src.services.fast_lane.shadow import ShadowSettings

    kwargs = _prepare_agent_kwargs(body)
    now = datetime.datetime.now(ZoneInfo(settings.vault_timezone))
    try:
        deps, calendar = get_fast_turn_deps(agent)
        ctx = context_module.assemble_fast_context(
            text=body.text, chat_id=body.chat_id, now=now, memory=deps.memory, events=deps.events,
            vault=deps.vault, reply_to=kwargs["reply_to"], selected_date=body.selected_date,
            attachments=kwargs["attachments"], places_path=deps.places_path,
            day_boundary_hour=settings.fast_lane_day_boundary_hour,
        )
    except Exception:
        # Nothing has been read or written yet: the message is today's router path's.
        logger.error("fast lane could not start; the router takes the message", exc_info=True,
                     extra={"event_type": "fast_turn", "route": "router_fallback"})
        result = await asyncio.to_thread(
            agent.handle_message, **kwargs, skill=None, prior_actions=None,
            stream_callback=(lambda text: emit({"text": text})) if stream else None,
            stage_callback=lambda s: emit({"stage": s}),
        )
        return _on_reply(response=result.response, route="router_fallback", receipt=None, result=result)

    fast_settings = ShadowSettings(model=settings.fast_parse_model, timeout_s=settings.fast_parse_timeout_s,
                                   day_boundary_hour=settings.fast_lane_day_boundary_hour,
                                   default_minutes=settings.default_event_duration)
    fast = await asyncio.to_thread(turn_module.run_fast_turn, ctx, deps, fast_settings,
                                   message_id=body.message_id, on_stage=lambda s: emit({"stage": s}))

    if fast.repeat:
        # Spec §10: answered from the first turn; nothing runs again, a skill included.
        if fast.receipt:
            emit({"receipt": fast.receipt})
        response = (fast.turn or {}).get("response") or (
            (fast.receipt or {}).get("text", "") if fast.route == "fast" else STILL_WORKING)
        return _on_reply(response=response, route=fast.route, receipt=fast.receipt)

    if fast.receipt:
        emit({"receipt": fast.receipt})
    # Held in `_fast_tasks`, never cancelled: the cap is on how long the reply
    # waits for Google, not on the syncs themselves (§8.1).
    syncs = _hold(asyncio.create_task(_settle_syncs(fast.turn, deps, calendar, now, emit))) if fast.turn else None

    # Every `on` message with a message_id leaves a turn record, so a repeat never
    # runs the agent twice (§10). Fallthrough turns have none from run_fast_turn;
    # it is saved before the agent starts, so a repeat arriving meanwhile is told so.
    record = fast.turn
    if record is None and body.message_id is not None:
        record = {"turn_id": act.new_turn_id(), "chat_id": body.chat_id, "message_id": body.message_id,
                  "created_at": now.isoformat(), "text": body.text, "route": fast.route,
                  "fallthrough_skill": fast.fallthrough_skill, "response": "", "lines": []}
        try:
            await asyncio.to_thread(act.save_turn, deps.actions_dir, record)
        except Exception:
            logger.error("fast lane could not save the fallthrough turn record", exc_info=True)

    result = None
    if fast.route == "fast":
        # Never the agent: the writes already ran, and it would make them twice.
        response = fast.receipt["text"] if fast.receipt else turn_module.NO_RECEIPT
    else:
        skill = None
        if fast.route != "router_fallback":
            if fast.lone_other:
                skill = _previous_skill(body.chat_id, now.date().isoformat())
            skill = skill or fast.fallthrough_skill
        try:
            result = await asyncio.to_thread(
                agent.handle_message, **kwargs, skill=skill, prior_actions=fast.ran or None,
                stream_callback=(lambda text: emit({"text": text})) if stream else None,
                stage_callback=lambda s: emit({"stage": s}),
            )
        except Exception:
            await _await_syncs(syncs)    # the fast lane's writes still get their Google entries
            if record is not None:
                # Kept, so a re-delivery is not run again; told it failed, not "still working".
                try:
                    await asyncio.to_thread(_patch_turn, deps.actions_dir, record,
                                            lambda turn: turn.__setitem__("response", AGENT_FAILED))
                except Exception:
                    logger.error("fast lane could not record the failure on turn %s", record.get("turn_id"),
                                 exc_info=True)
            raise
        response = result.response

    await _await_syncs(syncs)

    saved = None
    if record is not None:
        def set_response(turn: dict) -> None:
            turn["response"] = response

        try:
            saved = await asyncio.to_thread(_patch_turn, deps.actions_dir, record, set_response)
        except Exception:
            logger.error("fast lane could not save the response on turn %s", record.get("turn_id"), exc_info=True)
    receipt = fast.receipt
    if saved is not None and saved.get("lines"):
        try:
            receipt = render_receipt(saved, now)     # with each line's sync result
        except Exception:
            logger.error("fast lane receipt failed to re-render on turn %s", record.get("turn_id"), exc_info=True)
    return _on_reply(response=response, route=fast.route, receipt=receipt, result=result)


async def _await_syncs(syncs) -> None:
    """Wait for the syncs up to the cap, without cancelling them: late lines still reach Google."""
    if syncs is None:
        return
    done, _ = await asyncio.wait({syncs}, timeout=SYNC_CAP_S)
    if not done:
        logger.warning("fast lane calendar sync still running after %ss; replying without it", SYNC_CAP_S)
    elif not syncs.cancelled() and syncs.exception() is not None:
        logger.error("fast lane calendar syncs failed", exc_info=syncs.exception())


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def _log_responded(body: MessageRequest, final: dict, *, streamed: bool) -> None:
    logger.info("message_responded", extra={
        "event_type": "message_responded", "chat_id": body.chat_id,
        "response_length": len(final["response"]), "route": final["route"],
        "awaiting_confirmation": final["awaiting_confirmation"],
        "pending_action_id": final["pending_action_id"], "streamed": streamed,
    })


async def _handle_on(body: MessageRequest, agent, *, stream: bool):
    """`FAST_LANE_MODE=on`: the fast lane first, then the skill or the router for what it leaves."""
    if not stream:
        final = await _on_turn(body, agent, stream=False, emit=lambda payload: None)
        _log_responded(body, final, streamed=False)
        return final

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def emit(payload: dict) -> None:
        # The fast turn and the agent run in worker threads (the agent's parallel
        # tool calls in pool threads too); asyncio.Queue is not thread-safe.
        # After the stream closes the queue is unread and unbounded, so a late
        # put neither raises nor blocks; a closed loop is the one thing that can.
        try:
            loop.call_soon_threadsafe(queue.put_nowait, payload)
        except RuntimeError:
            pass

    async def _on_stream():
        task = _hold(asyncio.create_task(_on_turn(body, agent, stream=True, emit=emit)))
        while not task.done():
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=0.05)
            except asyncio.TimeoutError:
                continue
            yield _sse(payload)
        await asyncio.sleep(0)        # let the last thread-safe puts land
        while not queue.empty():
            yield _sse(queue.get_nowait())
        try:
            final = task.result()
        except Exception:
            logger.exception("fast lane turn failed")
            final = _on_reply(response="❌ Something went wrong while handling that.", route="error", receipt=None)
        _log_responded(body, final, streamed=True)
        yield _sse({"done": True, "response": final})

    return StreamingResponse(_on_stream(), media_type="text/event-stream")


@router.post("/message")
async def handle_message(body: MessageRequest, stream: bool = False):
    agent = get_agent()
    if not agent:
        raise HTTPException(status_code=503, detail="Agent service not initialized (missing API key?)")

    attachment_types = [a.type for a in body.attachments] if body.attachments else []
    logger.info(
        "message_received",
        extra={
            "event_type": "message_received",
            "chat_id": body.chat_id,
            "text_length": len(body.text),
            "attachment_types": attachment_types,
            "has_reply_to": body.reply_to is not None,
            "has_forwarded_from": body.forwarded_from is not None,
        },
    )
    # The same facts on the span, not only in the log. A missing reply_to or
    # selected_date is the shape of bug that cost two rounds on 2026-09-12,
    # and it was invisible in Phoenix: 30 spans for that minute mentioned
    # neither field, so the only way to see it was grepping this log by
    # timestamp. Now one trace answers "what context did this turn have".
    set_payload_provenance(
        text_length=len(body.text),
        has_reply_to=body.reply_to is not None,
        reply_to_from=body.reply_to.from_role if body.reply_to else None,
        selected_date=body.selected_date,
        has_forwarded_from=body.forwarded_from is not None,
        attachment_types=attachment_types,
    )

    if settings.fast_lane_mode == "on":
        return await _handle_on(body, agent, stream=stream)

    _start_fast_lane_shadow(body)

    kwargs = _prepare_agent_kwargs(body)

    if not stream:
        # Non-streaming path — unchanged behaviour.
        result = await asyncio.to_thread(agent.handle_message, **kwargs)
        logger.info(
            "message_responded",
            extra={
                "event_type": "message_responded",
                "chat_id": body.chat_id,
                "response_length": len(result.response),
                "awaiting_confirmation": result.awaiting_confirmation,
                "pending_action_id": result.pending_action_id,
            },
        )
        return {
            "response": result.response,
            "awaiting_confirmation": result.awaiting_confirmation,
            "pending_action_id": result.pending_action_id,
            "confirmation_choices": result.confirmation_choices,
        }

    # Streaming path — return Server-Sent Events.
    # The agent runs in a thread pool; text chunks are forwarded via a queue.
    queue: asyncio.Queue = asyncio.Queue()
    _SENTINEL = object()

    def on_chunk(text: str) -> None:
        """Called from the agent thread; asyncio Queue.put_nowait is thread-safe."""
        queue.put_nowait(text)

    async def _producer():
        return await asyncio.to_thread(
            agent.handle_message,
            **kwargs,
            stream_callback=on_chunk,
        )

    async def _stream_iter():
        producer_task = asyncio.create_task(_producer())
        # Drain text chunks while producer is running.
        while True:
            try:
                chunk = queue.get_nowait()
            except asyncio.QueueEmpty:
                if producer_task.done():
                    break
                await asyncio.sleep(0)
                continue
            if chunk is _SENTINEL:
                break
            yield f"data: {json.dumps({'text': chunk})}\n\n"
        # Drain any remaining chunks that arrived before the break.
        while not queue.empty():
            chunk = queue.get_nowait()
            if chunk is not _SENTINEL:
                yield f"data: {json.dumps({'text': chunk})}\n\n"
        # Emit the final done event with the complete response object.
        result = await producer_task
        logger.info(
            "message_responded",
            extra={
                "event_type": "message_responded",
                "chat_id": body.chat_id,
                "response_length": len(result.response),
                "awaiting_confirmation": result.awaiting_confirmation,
                "pending_action_id": result.pending_action_id,
                "streamed": True,
            },
        )
        final_payload = {
            "response": result.response,
            "awaiting_confirmation": result.awaiting_confirmation,
            "pending_action_id": result.pending_action_id,
            "confirmation_choices": result.confirmation_choices,
        }
        yield f"data: {json.dumps({'done': True, 'response': final_payload})}\n\n"

    return StreamingResponse(_stream_iter(), media_type="text/event-stream")


@router.post("/message/confirm")
def handle_confirmation(body: ConfirmationRequest):
    agent = get_agent()
    if not agent:
        raise HTTPException(status_code=503, detail="Agent service not initialized")

    logger.info(
        "confirmation_received",
        extra={
            "event_type": "confirmation_received",
            "chat_id": body.chat_id,
            "pending_action_id": body.action_id,
            "response": body.response,
        },
    )

    result = agent.handle_confirmation(body.chat_id, body.action_id, body.response)

    logger.info(
        "confirmation_responded",
        extra={
            "event_type": "confirmation_responded",
            "chat_id": body.chat_id,
            "pending_action_id": result.pending_action_id,
            "awaiting_confirmation": result.awaiting_confirmation,
            "response_length": len(result.response),
        },
    )
    return {
        "response": result.response,
        "awaiting_confirmation": result.awaiting_confirmation,
        "pending_action_id": result.pending_action_id,
        "confirmation_choices": result.confirmation_choices,
    }
