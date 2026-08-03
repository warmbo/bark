"""Member-note API. Contract: docs/moderation-workflows.md#notes."""

from fastapi import APIRouter, Request

from database.engine import session_scope
from database.models.moderation import UserNote
from services.response import (
    api_error,
    api_forbidden,
    api_not_found,
    api_success,
    check_api_permission,
    get_module_min_role,
)

router = APIRouter(tags=["api-notes"])


async def _can_manage_notes(request: Request, guild_id: str) -> bool:
    """Notes are moderation data, so honor the guild's module role override."""
    await get_module_min_role("moderation", guild_id)
    return check_api_permission(request, "moderation.notes.create", guild_id)


async def _can_view_notes(request: Request, guild_id: str) -> bool:
    """Private moderation notes are visible only to the configured moderation role."""
    await get_module_min_role("moderation", guild_id)
    return check_api_permission(request, "moderation.notes.view", guild_id)


def _note_content(data: dict) -> str:
    content = str(data.get("content", "")).strip()
    if not content:
        raise ValueError("Note content is required")
    if len(content) > 2000:
        raise ValueError("Note content must be 2,000 characters or fewer")
    return content


@router.get("/guilds/{guild_id}/notes")
async def list_notes(request: Request, guild_id: str):
    """List all user notes for a guild (most recent first)."""
    from sqlalchemy import desc, select

    gid = str(guild_id)
    if not await _can_view_notes(request, gid):
        return api_forbidden("Insufficient permissions to view notes")

    async with session_scope() as session:
        result = await session.execute(
            select(UserNote)
            .where(UserNote.guild_id == str(gid))
            .order_by(desc(UserNote.created_at))
            .limit(100)
        )
        notes = result.scalars().all()

        return api_success(
            {
                "notes": [
                    {
                        "id": n.id,
                        "user_id": n.user_id,
                        "author_id": n.author_id,
                        "content": n.content,
                        "created_at": n.created_at.isoformat(),
                    }
                    for n in notes
                ],
                "meta": {
                    "count": len(notes),
                    "guild_id": gid,
                },
            }
        )


@router.get("/guilds/{guild_id}/notes/user/{user_id}")
async def list_notes_for_user(request: Request, guild_id: str, user_id: str):
    """List notes for a specific user."""
    from sqlalchemy import desc, select

    gid = str(guild_id)
    if not await _can_view_notes(request, gid):
        return api_forbidden("Insufficient permissions to view notes")

    async with session_scope() as session:
        result = await session.execute(
            select(UserNote)
            .where(
                UserNote.guild_id == str(gid),
                UserNote.user_id == user_id,
            )
            .order_by(desc(UserNote.created_at))
        )
        notes = result.scalars().all()

        return api_success(
            {
                "notes": [
                    {
                        "id": n.id,
                        "author_id": n.author_id,
                        "content": n.content,
                        "created_at": n.created_at.isoformat(),
                    }
                    for n in notes
                ],
            }
        )


@router.post("/guilds/{guild_id}/notes")
async def create_note(request: Request, guild_id: str):
    """Create a user note."""
    data = await request.json()
    gid = str(guild_id)
    if not await _can_manage_notes(request, gid):
        return api_forbidden("Insufficient permissions to create notes")
    user_id = str(data.get("user_id", "")).strip()
    if not user_id.isdigit():
        return api_error("user_id must be a valid Discord user ID")
    try:
        content = _note_content(data)
    except ValueError as error:
        return api_error(str(error))
    author_id = str(request.session.get("user", {}).get("id") or "dashboard")

    async with session_scope() as session:
        note = UserNote(
            guild_id=str(gid),
            user_id=user_id,
            author_id=author_id,
            content=content,
        )
        session.add(note)
        await session.commit()

        return api_success(
            {
                "success": True,
                "id": note.id,
            }
        )


@router.patch("/guilds/{guild_id}/notes/{note_id}")
async def update_note(request: Request, guild_id: str, note_id: int):
    """Update a note's content."""
    from sqlalchemy import select

    gid = str(guild_id)
    data = await request.json()
    if not await _can_manage_notes(request, gid):
        return api_forbidden("Insufficient permissions to update notes")
    try:
        content = _note_content(data)
    except ValueError as error:
        return api_error(str(error))

    async with session_scope() as session:
        result = await session.execute(
            select(UserNote).where(UserNote.id == note_id, UserNote.guild_id == str(gid))
        )
        note = result.scalar_one_or_none()
        if note is None:
            return api_error("Note not found", status_code=404)
        note.content = content
        await session.commit()
        return api_success({"id": note.id, "content": note.content})


@router.delete("/guilds/{guild_id}/notes/{note_id}")
async def delete_note(request: Request, guild_id: str, note_id: int):
    """Delete a user note."""
    from sqlalchemy import select

    gid = str(guild_id)
    if not await _can_manage_notes(request, gid):
        return api_forbidden("Insufficient permissions to delete notes")

    async with session_scope() as session:
        result = await session.execute(
            select(UserNote).where(UserNote.id == note_id, UserNote.guild_id == str(gid))
        )
        note = result.scalar_one_or_none()
        if note is None:
            return api_not_found("Note")
        await session.delete(note)
        await session.commit()
        return api_success({"deleted": True, "note_id": note_id})
