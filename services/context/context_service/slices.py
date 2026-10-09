import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from context_service.models import Artifact, Fact, Turn, iso

TURN_LIMIT = 10


async def _facts(session: AsyncSession, conversation_id: uuid.UUID) -> dict[str, dict[str, Any]]:
    rows = await session.scalars(select(Fact).where(Fact.conversation_id == conversation_id))
    return {fact.key: {"value": fact.value, "version": fact.version} for fact in rows}


async def orchestrator_slice(session: AsyncSession, conversation_id: uuid.UUID) -> dict[str, Any]:
    latest_turns = await session.scalars(
        select(Turn)
        .where(Turn.conversation_id == conversation_id)
        .order_by(Turn.created_at.desc(), Turn.id.desc())
        .limit(TURN_LIMIT)
    )
    artifacts = await session.scalars(
        select(Artifact)
        .where(Artifact.conversation_id == conversation_id)
        .order_by(Artifact.created_at, Artifact.id)
    )
    return {
        "conversation_id": str(conversation_id),
        "turns": [
            {
                "id": str(turn.id),
                "channel": turn.channel,
                "role": turn.role,
                "content": turn.content,
                "created_at": iso(turn.created_at),
            }
            for turn in reversed(latest_turns.all())
        ],
        "facts": await _facts(session, conversation_id),
        "artifacts": [
            {"id": str(a.id), "type": a.type, "created_at": iso(a.created_at)} for a in artifacts
        ],
    }


async def specialist_slice(session: AsyncSession, conversation_id: uuid.UUID) -> dict[str, Any]:
    facts = await _facts(session, conversation_id)
    customer = facts.get("current_customer")
    return {
        "conversation_id": str(conversation_id),
        "facts": {"current_customer": customer}
        if customer and customer["value"] is not None
        else {},
    }
