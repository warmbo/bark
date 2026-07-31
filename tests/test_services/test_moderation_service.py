"""Moderation service concurrency tests."""

import asyncio

import pytest
from sqlalchemy import select

from database.engine import session_scope
from database.models.guild import Guild
from database.models.moderation import ModerationCase, Warning
from services.moderation_service import ModerationService


@pytest.mark.asyncio
async def test_concurrent_case_creation_allocates_unique_case_numbers(db):
    async with session_scope() as session:
        session.add(Guild(discord_id="1", name="Guild"))
        await session.commit()

    case_numbers = await asyncio.gather(
        *[
            ModerationService.create_case(
                guild_id=1,
                action_type="warn",
                target_id=str(index),
                target_tag=f"User {index}",
                moderator_id="99",
                moderator_tag="Moderator",
                reason="Concurrent test",
                warning_user_id=str(index),
            )
            for index in range(8)
        ]
    )

    assert sorted(case_numbers) == list(range(1, 9))
    async with session_scope() as session:
        rows = (
            (await session.execute(select(ModerationCase).where(ModerationCase.guild_id == "1")))
            .scalars()
            .all()
        )
    assert len(rows) == 8
    async with session_scope() as session:
        warnings = (
            (await session.execute(select(Warning).where(Warning.guild_id == "1"))).scalars().all()
        )
    assert len(warnings) == 8
