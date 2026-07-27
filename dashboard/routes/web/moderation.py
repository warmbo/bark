"""
Moderation web routes.
"""

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

router = APIRouter(tags=["web-moderation"])


@router.get("/moderation", response_class=RedirectResponse)
async def moderation_page(request: Request, guild_id: int):
    """Redirect to the unified module workspace."""
    return RedirectResponse(url=f"/guild/{guild_id}/modules/moderation")
