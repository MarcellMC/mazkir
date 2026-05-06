"""Natural language message endpoint — agent loop."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.auth import verify_api_key

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
    attachments: list[AttachmentModel] | None = None
    reply_to: ReplyContextModel | None = None
    forwarded_from: ForwardContextModel | None = None


class ConfirmationRequest(BaseModel):
    chat_id: int
    action_id: str
    response: str


@router.post("/message")
def handle_message(body: MessageRequest):
    from src.main import get_agent
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
    }


@router.post("/message/confirm")
def handle_confirmation(body: ConfirmationRequest):
    from src.main import get_agent
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
    }
