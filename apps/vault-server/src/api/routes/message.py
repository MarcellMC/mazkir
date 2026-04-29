"""Natural language message endpoint — agent loop."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.auth import verify_api_key

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
    from src.main import get_agent
    agent = get_agent()
    if not agent:
        raise HTTPException(status_code=503, detail="Agent service not initialized")

    result = agent.handle_confirmation(body.chat_id, body.action_id, body.response)
    return {
        "response": result.response,
        "awaiting_confirmation": result.awaiting_confirmation,
        "pending_action_id": result.pending_action_id,
    }
