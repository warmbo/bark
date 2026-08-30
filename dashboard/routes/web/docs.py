"""Public documentation / knowledge-base wiki routes.

Every command, setting, and module of the running Bark instance is documented
on public, linkable pages generated live from the module registry (so the docs
never drift from code). All routes are public (no auth) and serve self-contained
wiki templates under ``templates/docs/``.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from config import config
from services import docs_registry

router = APIRouter(prefix="/docs", tags=["docs"])


def _ctx(request: Request) -> dict:
    """Build the shared wiki template context from the live bot registry."""
    bot = getattr(request.state, "bot", None)
    manager = getattr(bot, "modules", None) if bot is not None else None
    return {
        "config": config,
        "public_url": docs_registry.public_url(config),
        "group": docs_registry.command_group_name(manager),
        "docs_base": "docs/base.html",
        "modules": docs_registry.collect_modules(manager),
        "commands": docs_registry.collect_commands(manager),
        "settings": docs_registry.collect_settings(manager),
    }


def _module_page(ctx: dict, name: str):
    return next((m for m in ctx["modules"] if m["name"] == name), None)


@router.get("", response_class=HTMLResponse)
async def docs_index(request: Request):
    ctx = _ctx(request)
    ctx["active"] = "home"
    return request.app.state.templates.TemplateResponse(request, "docs/index.html", ctx)


@router.get("/modules", response_class=HTMLResponse)
async def docs_modules(request: Request):
    ctx = _ctx(request)
    ctx["active"] = "modules"
    return request.app.state.templates.TemplateResponse(request, "docs/modules.html", ctx)


@router.get("/modules/{name}", response_class=HTMLResponse)
async def docs_module(request: Request, name: str):
    ctx = _ctx(request)
    module = _module_page(ctx, name)
    if module is None:
        ctx["not_found"] = f"Module `{name}`"
        return request.app.state.templates.TemplateResponse(request, "docs/not_found.html", ctx)
    ctx["module"] = module
    ctx["active"] = "modules"
    return request.app.state.templates.TemplateResponse(request, "docs/module.html", ctx)


@router.get("/commands", response_class=HTMLResponse)
async def docs_commands(request: Request):
    ctx = _ctx(request)
    ctx["active"] = "commands"
    return request.app.state.templates.TemplateResponse(request, "docs/commands.html", ctx)


@router.get("/commands/{command:path}", response_class=HTMLResponse)
async def docs_command(request: Request, command: str):
    ctx = _ctx(request)
    target = command.rstrip("/").lower()
    cmd = next((c for c in ctx["commands"] if c["path"].lower() == target), None)
    if cmd is None:
        ctx["not_found"] = f"Command `/{ctx['group']} {target}`"
        return request.app.state.templates.TemplateResponse(request, "docs/not_found.html", ctx)
    ctx["command"] = cmd
    ctx["active"] = "commands"
    return request.app.state.templates.TemplateResponse(request, "docs/command.html", ctx)


@router.get("/settings", response_class=HTMLResponse)
async def docs_settings(request: Request):
    ctx = _ctx(request)
    ctx["active"] = "settings"
    return request.app.state.templates.TemplateResponse(request, "docs/settings.html", ctx)


@router.get("/settings/{module}", response_class=HTMLResponse)
async def docs_settings_module(request: Request, module: str):
    ctx = _ctx(request)
    entry = next((s for s in ctx["settings"] if s["module"] == module), None)
    if entry is None:
        ctx["not_found"] = f"Settings for module `{module}`"
        return request.app.state.templates.TemplateResponse(request, "docs/not_found.html", ctx)
    ctx["setting_group"] = entry
    ctx["active"] = "settings"
    return request.app.state.templates.TemplateResponse(request, "docs/settings_module.html", ctx)


@router.get("/permissions", response_class=HTMLResponse)
async def docs_permissions(request: Request):
    ctx = _ctx(request)
    ctx["permissions"] = docs_registry.collect_permissions()
    ctx["active"] = "permissions"
    return request.app.state.templates.TemplateResponse(request, "docs/permissions.html", ctx)
