"""Natural language message endpoint — agent loop."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.auth import verify_api_key
from src.main import get_agent

router = APIRouter(tags=["message"], dependencies=[Depends(verify_api_key)])


class MessageRequest(BaseModel):
    text: str
    chat_id: int = 0


class ConfirmationRequest(BaseModel):
    chat_id: int
    action_id: str
    response: str


@router.post("/message")
def handle_message(body: MessageRequest):
    agent = get_agent()
    if not agent:
        raise HTTPException(status_code=503, detail="Agent service not initialized (missing API key?)")

    result = agent.handle_message(body.text, body.chat_id)
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
