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
