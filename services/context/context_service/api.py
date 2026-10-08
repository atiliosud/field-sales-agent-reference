import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Path, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from context_service import slices, telemetry
from context_service.auth import Caller, authenticated
from context_service.db import get_session
from context_service.errors import forbidden, invalid_input, not_found
from context_service.facts import put_fact
from context_service.models import Artifact, Conversation, Turn, iso

ROLES = ("orchestrator", "specialist")

router = APIRouter()


class TurnIn(BaseModel):
    channel: Literal["text", "voice"]
    role: Literal["user", "orchestrator", "specialist"]
    content: str = Field(min_length=1)


class FactIn(BaseModel):
    value: Any


class ArtifactIn(BaseModel):
    type: str = Field(min_length=1, max_length=100)
    payload: Any


def agent_role(
    caller: Annotated[Caller, Depends(authenticated)],
    x_agent_role: Annotated[str | None, Header()] = None,
) -> str:
    if x_agent_role not in ROLES:
        raise invalid_input("The X-Agent-Role header must be orchestrator or specialist.")
    return x_agent_role


def orchestrator_only(role: Annotated[str, Depends(agent_role)]) -> str:
    if role != "orchestrator":
        raise forbidden("Only the orchestrator can write facts.")
    return role


def requested_agent(
    role: Annotated[str, Depends(agent_role)],
    agent: Annotated[Literal["orchestrator", "specialist"], Query()],
) -> str:
    if agent != role:
        raise invalid_input("The agent parameter must match the X-Agent-Role header.")
    return agent


async def owned_conversation(
    conversation_id: uuid.UUID,
    caller: Annotated[Caller, Depends(authenticated)],
    role: Annotated[str, Depends(agent_role)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Conversation:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise not_found(f"Conversation {conversation_id} was not found.")
    if conversation.salesperson_id != caller.id:
        raise forbidden(f"Conversation {conversation_id} is not yours.")
    return conversation


def if_match_version(if_match: Annotated[str | None, Header()] = None) -> int:
    try:
        version = int((if_match or "").strip().strip('"'))
    except ValueError:
        version = -1
    if version < 0:
        raise invalid_input("The If-Match header must be the current version of the fact.")
    return version


@router.post("/conversations", status_code=201, dependencies=[Depends(agent_role)])
async def create_conversation(
    caller: Annotated[Caller, Depends(authenticated)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str]:
    conversation = Conversation(salesperson_id=caller.id)
    session.add(conversation)
    await session.commit()
    telemetry.set_attribute("session.id", str(conversation.id))
    return {
        "id": str(conversation.id),
        "salesperson_id": conversation.salesperson_id,
        "created_at": iso(conversation.created_at),
    }


@router.get("/conversations/{conversation_id}/context")
async def get_context(
    agent: Annotated[str, Depends(requested_agent)],
    conversation: Annotated[Conversation, Depends(owned_conversation)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    if agent == "orchestrator":
        return await slices.orchestrator_slice(session, conversation.id)
    return await slices.specialist_slice(session, conversation.id)


@router.post("/conversations/{conversation_id}/turns", status_code=201)
async def add_turn(
    body: TurnIn,
    conversation: Annotated[Conversation, Depends(owned_conversation)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str]:
    turn = Turn(
        conversation_id=conversation.id,
        channel=body.channel,
        role=body.role,
        content=body.content,
    )
    session.add(turn)
    await session.commit()
    return {"id": str(turn.id), "created_at": iso(turn.created_at)}


@router.put("/conversations/{conversation_id}/facts/{key}")
async def write_fact(
    body: FactIn,
    key: Annotated[str, Path(min_length=1, max_length=100)],
    role: Annotated[str, Depends(orchestrator_only)],
    conversation: Annotated[Conversation, Depends(owned_conversation)],
    expected_version: Annotated[int, Depends(if_match_version)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    return await put_fact(session, conversation.id, key, body.value, expected_version, role)


@router.post("/conversations/{conversation_id}/artifacts", status_code=201)
async def add_artifact(
    body: ArtifactIn,
    conversation: Annotated[Conversation, Depends(owned_conversation)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str]:
    artifact = Artifact(conversation_id=conversation.id, type=body.type, payload=body.payload)
    session.add(artifact)
    await session.commit()
    return {"id": str(artifact.id)}
