"""
Ruleset engine — condition matching, trigger checking, and effect execution
for the ruleset-based AutoMod system.

Each function is stateless and receives its dependencies explicitly.
The ModerationModule wires these into the message-handling pipeline.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import discord

logger = logging.getLogger("bark.ruleset_engine")

INVITE_REGEX = re.compile(
    r"(?:discord\.(?:gg|io|me|com/invite)/|discord\.com/invite/)[a-zA-Z0-9_\-]+",
    re.IGNORECASE,
)

SCAM_DOMAINS = {
    "steamcommunit.ru",
    "discord-nitro.xyz",
    "discordgift.com",
    "steam-gift.ru",
    "discord.xyz.gift",
    "free-nitro.pro",
    "steamcommunit.com",
    "nitro-free.xyz",
    "free-discordnitro.com",
    "givvn.com",
    "steamcommunity.vip",
    "steam-list.com",
}

WEBHOOK_SCAM_PATTERNS = [
    re.compile(r"discord\s+nitro\s+(free|giveaway|generator)", re.IGNORECASE),
    re.compile(r"steamcommunity\.com/gift", re.IGNORECASE),
    re.compile(r"free\s+nitro\s+@everyone", re.IGNORECASE),
    re.compile(r"gift\s*\.?\s*nitro", re.IGNORECASE),
]

LINK_REGEX = re.compile(
    r"(?i)([a-z\d]+://)([\w\-._~:/?#\[\]@!$&'()*+,;%=]+"
    r"(?:(?:\.[\w_-]+)+))([\w.,@?^=%&:/~+#-]*[\w@?^=%&/~+#-])"
)


# ── Condition checking ─────────────────────────────────────────────


def check_ruleset_conditions(
    member: Any | None,
    message: Any | None,
    ruleset: Any,
) -> tuple[bool, str]:
    """Check scoped conditions on a ruleset. Returns (passes, reason_if_failed)."""
    if not message and not member:
        return True, ""

    channel = getattr(message, "channel", None) if message else None
    guild = getattr(message, "guild", None) if message else None

    # ── Bot/user scoping ──
    if message:
        is_bot = getattr(message.author, "bot", False) if message.author else False
        if ruleset.only_bots and not is_bot:
            return False, "rule only applies to bots"
        if ruleset.ignore_bots and is_bot:
            return False, "bot ignored"
    elif member:
        if ruleset.only_bots and not getattr(member, "bot", False):
            return False, "rule only applies to bots"
        if ruleset.ignore_bots and getattr(member, "bot", False):
            return False, "bot ignored"

    # ── Ignored roles ──
    target = member or (message.author if message else None)
    if target and hasattr(target, "roles"):
        ignored = _json_list(ruleset.ignored_roles)
        if ignored:
            for role in target.roles:
                if str(role.id) in ignored:
                    return False, f"ignored role {role.name}"

    # ── Required roles ──
    if target and hasattr(target, "roles"):
        required = _json_list(ruleset.require_roles)
        if required:
            user_role_ids = {str(r.id) for r in target.roles}
            if ruleset.require_all_roles:
                if not all(r in user_role_ids for r in required):
                    return False, "missing required role"
            else:
                if not any(r in user_role_ids for r in required):
                    return False, "missing any required role"

    # ── Channel conditions ──
    if channel:
        channel_id = str(channel.id)
        # Ignored channels
        ignored_chs = _json_list(ruleset.ignored_channels)
        if ignored_chs and channel_id in ignored_chs:
            return False, "channel is ignored"

        # Active channels (if set, only match these)
        active_chs = _json_list(ruleset.active_channels)
        if active_chs and channel_id not in active_chs:
            return False, "channel not in active list"

        # Ignored categories
        category_id = str(channel.category_id) if channel.category_id else ""
        ignored_cats = _json_list(ruleset.ignored_categories)
        if ignored_cats and category_id in ignored_cats:
            return False, "category is ignored"

        # Active categories
        active_cats = _json_list(ruleset.active_categories)
        if active_cats and category_id not in active_cats:
            return False, "category not in active list"

    # ── Message scope (new vs edited) ──
    if message and hasattr(message, "_edited"):
        # discord.py doesn't expose "is this an edit" directly in on_message
        # but we can check if the message has been edited via raw data
        pass  # handled by event subscription in the module

    # ── Account age ──
    if target:
        created_at = getattr(target, "created_at", None)
        if created_at and ruleset.account_age_minutes_min > 0:
            age_minutes = (datetime.now(timezone.utc) - created_at).total_seconds() / 60
            if age_minutes < ruleset.account_age_minutes_min:
                return (
                    False,
                    f"account too young ({age_minutes:.0f}m < {ruleset.account_age_minutes_min}m)",
                )
        if created_at and ruleset.account_age_minutes_max > 0:
            age_minutes = (datetime.now(timezone.utc) - created_at).total_seconds() / 60
            if age_minutes > ruleset.account_age_minutes_max:
                return (
                    False,
                    f"account too old ({age_minutes:.0f}m > {ruleset.account_age_minutes_max}m)",
                )

    # ── Member duration ──
    if target and guild:
        joined_at = getattr(target, "joined_at", None)
        if joined_at:
            member_minutes = (datetime.now(timezone.utc) - joined_at).total_seconds() / 60
            if (
                ruleset.member_duration_minutes_min > 0
                and member_minutes < ruleset.member_duration_minutes_min
            ):
                return (
                    False,
                    f"member too new ({member_minutes:.0f}m < {ruleset.member_duration_minutes_min}m)",
                )
            if (
                ruleset.member_duration_minutes_max > 0
                and member_minutes > ruleset.member_duration_minutes_max
            ):
                return (
                    False,
                    f"member been here too long ({member_minutes:.0f}m > {ruleset.member_duration_minutes_max}m)",
                )

    return True, ""


def check_rule_conditions(
    message: Any,
    rule: Any,
) -> tuple[bool, str]:
    """Check per-rule conditions (JSON overrides from rule.conditions)."""
    conds = _json_dict(rule.conditions)
    if not conds:
        return True, ""

    # Per-rule ignored roles/channels override the ruleset's conditions
    if message:
        ignored_roles = conds.get("ignored_roles", [])
        if ignored_roles and message.author and hasattr(message.author, "roles"):
            for role in message.author.roles:
                if str(role.id) in ignored_roles:
                    return False, "rule-level ignored role"

        ignored_channels = conds.get("ignored_channels", [])
        if ignored_channels and message.channel:
            if str(message.channel.id) in ignored_channels:
                return False, "rule-level ignored channel"

    return True, ""


# ── Trigger checkers ───────────────────────────────────────────────


async def check_trigger(
    message: Any,
    trigger_type: str,
    trigger_config: dict,
    rule_id: int,
    module_instance,
) -> tuple[bool, str]:
    """Check if a message matches the given trigger. Returns (triggered, reason)."""
    checks = {
        # Core triggers (keepers)
        "message_spam": _check_spam,
        "mass_mention": _check_mention,
        "invite_link": _check_invite,
        "banned_words": _check_word_denylist,
        "banned_domains": _check_link_denylist,
        "scam_link": _check_scam_link,
        "regex_match": _check_regex_match,
        "duplicate_message": _check_duplicate_message,
        "all_caps": _check_all_caps,
        "attachment_spam": _check_attachment_rate,
        "any_link": _check_any_link,
        # Aliases (backward compat with old names)
        "spam": _check_spam,
        "user_message_rate": _check_spam,
        "mention": _check_mention,
        "user_mention_rate": _check_mention,
        "invite": _check_invite,
        "word_denylist": _check_word_denylist,
        "link_denylist": _check_link_denylist,
        "content_spam": _check_duplicate_message,
        "attachment_rate": _check_attachment_rate,
        "regex": _check_regex_match,
    }

    checker = checks.get(trigger_type)
    if checker is None:
        logger.warning("Unknown trigger type: %s (rule %d)", trigger_type, rule_id)
        return False, ""

    try:
        return await checker(message, trigger_config, rule_id, module_instance)
    except Exception:
        logger.exception("Error in trigger check %s (rule %d)", trigger_type, rule_id)
        return False, ""


async def _check_spam(message, cfg, rule_id, module):
    """X messages from same user in Y seconds (cross-channel)."""
    threshold = cfg.get("threshold", 5)
    window = cfg.get("window_seconds", 10)
    track = module._message_track[message.guild.id][message.author.id]
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=window)
    while track and track[0] < cutoff:
        track.popleft()
    track.append(now)
    if len(track) >= threshold:
        return True, f"Spam ({len(track)} msgs/{window}s)"
    return False, ""


async def _check_invite(message, cfg, rule_id, module):
    """Discord invite link in message."""
    if INVITE_REGEX.search(message.content or ""):
        return True, "Invite link"
    return False, ""


async def _check_mention(message, cfg, rule_id, module):
    """Excessive @mentions in a single message."""
    threshold = cfg.get("threshold", 5)
    count = (
        len(message.mentions) + len(message.role_mentions) + (1 if message.mention_everyone else 0)
    )
    if count >= threshold:
        return True, f"Mention spam ({count} @)"
    return False, ""


async def _check_all_caps(message, cfg, rule_id, module):
    """Message exceeds a threshold of uppercase characters."""
    content = message.content or ""
    if not content:
        return False, ""
    min_caps = cfg.get("min_caps", 3)
    percent = cfg.get("percent", 100)
    letters = [c for c in content if c.isalpha()]
    if not letters:
        return False, ""
    upper_count = sum(1 for c in letters if c.isupper())
    upper_pct = int((upper_count / len(letters)) * 100) if letters else 0
    if upper_count >= min_caps and upper_pct >= percent:
        return True, f"All caps ({upper_pct}% uppercase)"
    return False, ""


async def _check_word_denylist(message, cfg, rule_id, module):
    """Message contains words from a denylist."""
    list_id = cfg.get("word_list_id")
    entries = await _get_list_entries(list_id, "word", module)
    if not entries:
        return False, ""
    content_lower = (message.content or "").lower()
    for word in entries:
        if word.lower() in content_lower:
            return True, f"Denied word: {word}"
    return False, ""


async def _check_link_denylist(message, cfg, rule_id, module):
    """Message contains links to denied domains."""
    list_id = cfg.get("word_list_id")
    entries = await _get_list_entries(list_id, "domain", module)
    if not entries:
        return False, ""
    domains = set(d.lower() for d in entries)
    found = _extract_domains(message.content or "")
    for f in found:
        for denied in domains:
            if f == denied or f.endswith("." + denied):
                return True, f"Denied domain: {f}"
    return False, ""


async def _check_regex_match(message, cfg, rule_id, module):
    """Message matches a regex pattern."""
    pattern = cfg.get("pattern", "")
    if not pattern:
        return False, ""
    try:
        if re.search(pattern, message.content or "", re.IGNORECASE):
            return True, f"Matched regex: {pattern}"
    except re.error:
        pass
    return False, ""


async def _check_duplicate_message(message, cfg, rule_id, module):
    """X consecutive identical messages from the same user."""
    threshold = cfg.get("threshold", 4)
    window = cfg.get("window_seconds", 60)
    now = datetime.now(timezone.utc)
    content = message.content or ""
    if not content:
        return False, ""
    cutoff = now - timedelta(seconds=window)
    # Simplified: check if last N messages from this user match
    if not hasattr(module, "_dup_track"):
        module._dup_track = {}
    guild_track = module._dup_track.setdefault(message.guild.id, {})
    user_track = guild_track.setdefault(message.author.id, [])
    # Prune old
    while user_track and user_track[0][0] < cutoff:
        user_track.pop(0)
    # Count consecutive identical
    count = 1
    for ts, prev_content in reversed(user_track):
        if prev_content == content:
            count += 1
        else:
            break
    user_track.append((now, content))
    if count >= threshold:
        return True, f"Duplicate message ({count}x identical)"
    return False, ""


async def _check_attachment_rate(message, cfg, rule_id, module):
    """X attachments by user in Y seconds."""
    threshold = cfg.get("threshold", 10)
    window = cfg.get("window_seconds", 60)
    attachments = len(message.attachments)
    if attachments == 0:
        return False, ""
    now = datetime.now(timezone.utc)
    track = module._message_track[message.guild.id].setdefault(f"_att_{message.author.id}", [])
    cutoff = now - timedelta(seconds=window)
    while track and track[0][0] < cutoff:
        track.pop(0)
    total_in_window = sum(c for _, c in track) + attachments
    track.append((now, attachments))
    if total_in_window >= threshold:
        return True, f"Attachment rate ({total_in_window} files/{window}s)"
    return False, ""


async def _check_scam_link(message, cfg, rule_id, module):
    """Message contains a known scam link.
    Checks per-guild configured scam domains/patterns, with built-in defaults as fallback."""
    content = message.content or ""

    # Try per-guild custom scam config
    guild_id = message.guild.id
    try:
        guild_scam = await module._get_setting(guild_id, "scam_protection", "domains", "")
        if guild_scam:
            custom_domains = [d.strip().lower() for d in guild_scam.split("\n") if d.strip()]
            for domain in custom_domains:
                if domain in content.lower():
                    return True, f"Custom scam domain: {domain}"

        guild_patterns = await module._get_setting(guild_id, "scam_protection", "patterns", "")
        if guild_patterns:
            for line in guild_patterns.split("\n"):
                line = line.strip()
                if line and re.search(line, content, re.IGNORECASE):
                    return True, "Custom scam pattern matched"
    except Exception:
        pass

    # Built-in defaults
    for domain in SCAM_DOMAINS:
        if domain in content.lower():
            return True, f"Scam domain: {domain}"

    for pat in WEBHOOK_SCAM_PATTERNS:
        if pat.search(content):
            return True, "Scam pattern matched"

    return False, ""


async def _check_any_link(message, cfg, rule_id, module):
    """Message contains any valid URL."""
    urls = _extract_urls(message.content or "")
    if urls:
        return True, f"Link detected: {urls[0]}"
    return False, ""


async def execute_effect(
    message: Any,
    effect_type: str,
    effect_config: dict,
    reason: str,
    module_instance,
) -> None:
    """Execute an AutoMod effect on a triggered message."""
    actions = {
        "delete": _effect_delete,
        "warn": _effect_warn,
        "timeout": _effect_timeout,
        "kick": _effect_kick,
        "ban": _effect_ban,
        "send_alert": _effect_send_alert,
        "delete_multiple": _effect_delete_multiple,
        "alert": _effect_send_alert,
    }

    handler = actions.get(effect_type)
    if handler is None:
        logger.warning("Unknown effect type: %s", effect_type)
        return

    try:
        await handler(message, effect_config, reason, module_instance)
    except Exception:
        logger.exception("Error in effect execution %s", effect_type)


async def _effect_delete(message, cfg, reason, module):
    """Delete the triggering message."""
    try:
        await message.delete()
    except Exception:
        pass


async def _effect_warn(message, cfg, reason, module):
    """Warn the user. Creates a case + warning record."""
    try:
        await message.delete()
    except Exception:
        pass
    from services.moderation_service import ModerationService

    bot_user = module.ctx.bot.user
    moderator_id = str(bot_user.id) if bot_user else ""
    moderator_tag = str(bot_user) if bot_user else "Bark"
    await ModerationService.create_case(
        guild_id=message.guild.id,
        action_type="warn",
        target_id=str(message.author.id),
        target_tag=str(message.author),
        moderator_id=moderator_id,
        moderator_tag=moderator_tag,
        reason=f"[AutoMod] {reason}",
        warning_user_id=str(message.author.id),
    )

    try:
        await message.channel.send(f"⚠️ {message.author.mention}, {reason}", delete_after=10)
    except Exception:
        pass


async def _effect_timeout(message, cfg, reason, module):
    """Timeout the user using Discord's native timeout."""
    if not isinstance(message.author, discord.Member):
        return
    duration_min = cfg.get("duration_minutes", 10)
    until = discord_utcnow() + timedelta(minutes=duration_min)
    try:
        await message.author.timeout(until, reason=f"[AutoMod] {reason}")
        try:
            await message.channel.send(
                f"⏱ {message.author.mention} timed out {duration_min}m. {reason}",
                delete_after=10,
            )
        except Exception:
            pass
    except Exception:
        pass


async def _effect_kick(message, cfg, reason, module):
    """Kick the user."""
    if not isinstance(message.author, type(message.guild.me)):
        return
    try:
        await message.author.kick(reason=f"[AutoMod] {reason}")
    except Exception:
        pass


async def _effect_ban(message, cfg, reason, module):
    """Ban the user, optionally with duration."""
    if not isinstance(message.author, type(message.guild.me)):
        return
    delete_days = cfg.get("delete_days", 0)
    try:
        await message.author.ban(reason=f"[AutoMod] {reason}", delete_message_days=delete_days)
    except Exception:
        pass


async def _effect_send_alert(message, cfg, reason, module):
    """Send a rich alert embed to a specified channel."""
    channel_id = cfg.get("channel_id") or message.channel.id
    channel = message.guild.get_channel(int(channel_id)) if channel_id else message.channel
    if not channel:
        return
    custom_msg = cfg.get("custom_message", "")
    import discord

    embed = discord.Embed(
        title="🚨 AutoMod Alert",
        color=discord.Color.red(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="Rule Triggered", value=reason, inline=False)
    embed.add_field(
        name="User",
        value=f"{message.author.mention} (`{message.author}`)",
        inline=True,
    )
    embed.add_field(
        name="Channel",
        value=message.channel.mention
        if hasattr(message.channel, "mention")
        else str(message.channel),
        inline=True,
    )
    if message.content:
        embed.add_field(
            name="Message",
            value=message.content[:1024],
            inline=False,
        )
    if custom_msg:
        embed.set_footer(text=custom_msg[:256])
    try:
        await channel.send(embed=embed)
    except Exception:
        pass


async def _effect_delete_multiple(message, cfg, reason, module):
    """Bulk-delete recent messages from the user in the same channel."""
    count = cfg.get("count", 5)
    max_age = cfg.get("max_age_seconds", 15)

    def _check(m):
        return (
            m.author.id == message.author.id
            and (datetime.now(timezone.utc) - m.created_at).total_seconds() < max_age
        )

    try:
        deleted = await message.channel.purge(limit=count + 10, check=_check)
        logger.info("Bulk-deleted %d messages for %s", len(deleted), message.author)
    except Exception:
        pass


async def _apply_escalation(message, action, strikes, reason, module):
    """Apply an escalated action (from the strike system)."""
    try:
        if action == "timeout":
            until = discord_utcnow() + timedelta(minutes=30)
            await message.author.timeout(until, reason=f"[AutoMod] Escalation ({strikes} strikes)")
            await message.channel.send(
                f"⏱ {message.author.mention} auto-escalated to timeout (strike {strikes})",
                delete_after=10,
            )
        elif action == "kick":
            await message.author.kick(reason=f"[AutoMod] Escalation ({strikes} strikes)")
            await message.channel.send(
                f"👢 {message.author.mention} auto-kicked (strike {strikes})"
            )
    except Exception:
        pass


# ── Helpers ──────────────────────────────────────────────────────────


def _json_list(value: str | list) -> list:
    """Parse a JSON string into a list, or return the list as-is."""
    if isinstance(value, list):
        return value
    try:
        return json.loads(value) if value else []
    except (json.JSONDecodeError, TypeError):
        return []


def _json_dict(value: str | dict) -> dict:
    """Parse a JSON string into a dict, or return the dict as-is."""
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value) if value else {}
    except (json.JSONDecodeError, TypeError):
        return {}


async def _get_list_entries(list_id: int | None, expected_type: str, module) -> list[str]:
    """Fetch entries from a WordList by ID (cached via module._wordlist_cache)."""
    if list_id is None:
        return []
    cache_key = f"{list_id}_{expected_type}"
    if hasattr(module, "_wordlist_cache") and cache_key in module._wordlist_cache:
        return module._wordlist_cache[cache_key]
    from sqlalchemy import select

    from database.engine import session_scope
    from database.models.ruleset import WordList

    async with session_scope() as session:
        result = await session.execute(select(WordList).where(WordList.id == list_id))
        wl = result.scalar_one_or_none()
        if not wl or wl.list_type != expected_type:
            return []
        entries = _json_list(wl.entries)
        if not hasattr(module, "_wordlist_cache"):
            module._wordlist_cache = {}
        module._wordlist_cache[cache_key] = entries
        return entries


def _extract_domains(text: str) -> list[str]:
    """Extract domain names from text."""
    if not text:
        return []
    urls = _extract_urls(text)
    domains = []
    for url in urls:
        try:
            from urllib.parse import urlparse

            parsed = urlparse(url)
            domain = parsed.netloc or parsed.path.split("/")[0]
            if domain:
                domains.append(domain.lower())
        except Exception:
            pass
    return domains


def _extract_urls(text: str) -> list[str]:
    """Extract all URLs from text."""
    if not text:
        return []
    return [m.group(0) for m in LINK_REGEX.finditer(text)]


def discord_utcnow():
    """Return current UTC datetime compatible with discord.py."""
    return datetime.now(timezone.utc)
