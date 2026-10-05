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
