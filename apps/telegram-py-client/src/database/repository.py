"""Data access layer for database operations."""
from datetime import datetime
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import Analysis, Message


class MessageRepository:
    """Repository for Message operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        telegram_id: int,
        chat_id: int,
        text: Optional[str],
        date: datetime,
        sender_id: Optional[int] = None,
        embedding: Optional[list] = None,
    ) -> Message:
        """Create a new message."""
        message = Message(
            telegram_id=telegram_id,
            chat_id=chat_id,
            sender_id=sender_id,
            text=text,
            date=date,
            embedding=embedding,
        )
        self.session.add(message)
        await self.session.commit()
        await self.session.refresh(message)
        return message

    async def get_by_telegram_id(self, telegram_id: int) -> Optional[Message]:
        """Get message by Telegram ID."""
        result = await self.session.execute(
            select(Message).where(Message.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    async def get_recent_messages(
        self, chat_id: int, limit: int = 100
    ) -> List[Message]:
        """Get recent messages from a chat."""
        result = await self.session.execute(
            select(Message)
            .where(Message.chat_id == chat_id)
            .order_by(Message.date.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def search_similar(
        self, embedding: list, limit: int = 10
    ) -> List[Message]:
        """Search for similar messages using vector similarity."""
        # Using pgvector's <-> operator for L2 distance
        result = await self.session.execute(
            select(Message)
            .where(Message.embedding.isnot(None))
            .order_by(Message.embedding.l2_distance(embedding))
            .limit(limit)
        )
        return list(result.scalars().all())


class AnalysisRepository:
    """Repository for Analysis operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        analysis_type: str,
        prompt: str,
        result: str,
        model_name: str,
    ) -> Analysis:
        """Create a new analysis record."""
        analysis = Analysis(
            analysis_type=analysis_type,
            prompt=prompt,
            result=result,
            model_name=model_name,
        )
        self.session.add(analysis)
        await self.session.commit()
        await self.session.refresh(analysis)
        return analysis

    async def get_recent(
        self, analysis_type: Optional[str] = None, limit: int = 10
    ) -> List[Analysis]:
        """Get recent analyses, optionally filtered by type."""
        query = select(Analysis).order_by(Analysis.created_at.desc()).limit(limit)

        if analysis_type:
            query = query.where(Analysis.analysis_type == analysis_type)

        result = await self.session.execute(query)
        return list(result.scalars().all())
