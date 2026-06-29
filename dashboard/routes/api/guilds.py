"""
Guilds API routes.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from database.engine import get_session
from database.models.guild import Guild as GuildModel

router = APIRouter(tags=["api-guilds"])


@router.get("/guilds")
async def list_guilds(request: Request):
    """List all guilds the bot is in."""
    bot = request.state.bot
    guilds = []
    for guild in bot.guilds:
        guilds.append({
            "id": guild.id,
            "name": guild.name,
            "member_count": guild.member_count,
            "owner_id": str(guild.owner_id),
            "icon_url": guild.icon.url if guild.icon else None,
        })
    return {"guilds": guilds}


@router.get("/guilds/{guild_id}")
async def get_guild(request: Request, guild_id: int):
    """Get detailed info about a guild."""
    bot = request.state.bot
    guild = bot.get_guild(guild_id)
    if guild is None:
        return JSONResponse({"error": "Guild not found"}, status_code=404)

    return {
        "id": guild.id,
        "name": guild.name,
        "member_count": guild.member_count,
        "owner_id": str(guild.owner_id),
        "owner_name": str(guild.owner) if guild.owner else "Unknown",
        "icon_url": guild.icon.url if guild.icon else None,
        "banner_url": guild.banner.url if guild.banner else None,
        "description": guild.description,
        "premium_tier": guild.premium_tier,
        "premium_subscriber_count": guild.premium_subscriber_count,
        "max_members": guild.max_members,
        "channels": len(guild.channels),
        "roles": len(guild.roles),
        "emojis": len(guild.emojis),
        "created_at": guild.created_at.isoformat() if guild.created_at else None,
    }


@router.get("/guilds/{guild_id}/stats")
async def get_guild_stats(request: Request, guild_id: int):
    """Get guild statistics."""
    bot = request.state.bot
    guild = bot.get_guild(guild_id)
    if guild is None:
        return JSONResponse({"error": "Guild not found"}, status_code=404)

    from sqlalchemy import select, func
    from database.models.moderation import ModerationCase

    async for session in get_session():
        # Count cases
        result = await session.execute(
            select(func.count(ModerationCase.id)).where(
                ModerationCase.guild_id == guild_id
            )
        )
        total_cases = result.scalar() or 0

        # Count by type
        result = await session.execute(
            select(
                ModerationCase.action_type,
                func.count(ModerationCase.id),
            ).where(ModerationCase.guild_id == guild_id).group_by(ModerationCase.action_type)
        )
        cases_by_type = {row[0]: row[1] for row in result}

        return {
            "members": guild.member_count,
            "channels": len(guild.channels),
            "roles": len(guild.roles),
            "boosts": guild.premium_subscriber_count,
            "total_cases": total_cases,
            "cases_by_type": cases_by_type,
        }
