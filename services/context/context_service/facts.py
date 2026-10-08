import uuid
from typing import Any

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from context_service.errors import ApiError, conflict
from context_service.models import Fact, utc_now


def _stale(key: str, current: int, expected: int) -> ApiError:
    return conflict(f"Fact {key} is at version {current}, not {expected}.")


async def put_fact(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    key: str,
    value: Any,
    expected_version: int,
    updated_by: str,
) -> dict[str, Any]:
    fact = await session.get(Fact, (conversation_id, key))
    current = fact.version if fact else 0
    if expected_version != current:
        raise _stale(key, current, expected_version)

    version = current + 1
    if fact is None:
        session.add(
            Fact(
                conversation_id=conversation_id,
                key=key,
                value=value,
                version=version,
                updated_by=updated_by,
            )
        )
    else:
        result = await session.execute(
            update(Fact)
            .where(
                Fact.conversation_id == conversation_id,
                Fact.key == key,
                Fact.version == expected_version,
            )
            .values(value=value, version=version, updated_by=updated_by, updated_at=utc_now())
        )
        if result.rowcount != 1:
            await session.rollback()
            raise _stale(key, current, expected_version)

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise _stale(key, current, expected_version) from None
    return {"key": key, "value": value, "version": version}
