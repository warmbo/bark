"""
AutoMod ruleset models — configurable, nameable rules with triggers/conditions/effects.

Supports the YAGPDB-inspired ruleset pattern: named groups of rules, each
with OR triggers, AND conditions, AND effects.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    String, Integer, Boolean, DateTime, Text, ForeignKey, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.engine import Base


class RuleSet(Base):
    """A named, toggleable group of AutoMod rules with scoped conditions."""

    __tablename__ = "rulesets"
    __table_args__ = (UniqueConstraint("guild_id", "name", name="uq_ruleset_guild_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("guilds.discord_id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False, default="Default")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    # ── Scoped conditions (apply to ALL rules in this ruleset) ──
    # Role/channel lists stored as JSON arrays of ID strings
    ignored_roles: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    require_roles: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    require_all_roles: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ignored_channels: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    active_channels: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    ignored_categories: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    active_categories: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    # Account / member age gates (values in minutes, 0 = no check)
    account_age_minutes_min: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    account_age_minutes_max: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    member_duration_minutes_min: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    member_duration_minutes_max: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Bot/user scoping
    only_bots: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ignore_bots: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Message scope
    check_new_messages: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    check_edited_messages: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    # ── Relationships ──
    rules = relationship(
        "Rule",
        back_populates="ruleset",
        cascade="all, delete-orphan",
        order_by="Rule.priority",
    )
    guild = relationship("Guild", back_populates="rulesets")

    def __repr__(self) -> str:
        return (
            f"<RuleSet id={self.id} guild={self.guild_id} "
            f"name='{self.name}' enabled={self.enabled}>"
        )


class Rule(Base):
    """A single AutoMod rule within a ruleset — one trigger + one effect + per-rule conditions."""

    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ruleset_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("rulesets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50)

    # ── Trigger ──
    # One of: spam, invite, mention, content_spam, all_caps, word_denylist,
    #         word_allowlist, link_denylist, link_allowlist, regex_match,
    #         regex_not_match, duplicate_message, attachment_rate, link_rate,
    #         user_message_rate, channel_message_rate, user_mention_rate,
    #         channel_mention_rate, character_limit_min, character_limit_max,
    #         scam_link, any_link, new_member, nickname_regex, nickname_word_denylist
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False)

    # JSON blob with trigger params, e.g.:
    #   {"threshold": 5, "window_seconds": 10}
    #   {"word_list_id": 1, "match_visually_similar": false}
    #   {"pattern": "\\bsuspicious\\b"}
    trigger_config: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    # ── Effect ──
    # One of: warn, delete, delete_multiple, timeout, kick, ban, mute,
    #         send_alert, send_message, enable_slowmode, give_role, remove_role,
    #         set_nickname, reset_violations, add_violation
    effect_type: Mapped[str] = mapped_column(String(24), nullable=False, default="warn")

    # JSON blob with effect params, e.g.:
    #   {"duration_minutes": 10, "custom_message": "No spam"}
    #   {"delete_days": 1} for ban
    effect_config: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    # ── Per-rule conditions (overrides ruleset scoped conditions) ──
    # JSON blob; keys match the scoped condition names in RuleSet
    conditions: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    ruleset = relationship("RuleSet", back_populates="rules")

    def __repr__(self) -> str:
        return (
            f"<Rule id={self.id} trigger='{self.trigger_type}' "
            f"effect='{self.effect_type}' enabled={self.enabled}>"
        )


class WordList(Base):
    """A reusable list of words or domains for denylist/allowlist triggers."""

    __tablename__ = "word_lists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("guilds.discord_id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    list_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="word"  # "word" or "domain"
    )
    # JSON array of strings
    entries: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    guild = relationship("Guild", back_populates="word_lists")

    def __repr__(self) -> str:
        return (
            f"<WordList id={self.id} guild={self.guild_id} "
            f"name='{self.name}' type='{self.list_type}'>"
        )
