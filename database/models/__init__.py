"""Database models — import all models here so they register with Base.metadata."""

from database.models.analytics import (
    ActivitySnapshot,
    DailyChannelStat,
    DailyEmojiStat,
)
from database.models.attachments import FileAttachment
from database.models.auto_voice import AutoVoiceChannel
from database.models.automod import AutoModConfig
from database.models.guild import Guild, GuildSetting
from database.models.logging import LogConfig
from database.models.moderation import AuditLog, ModerationCase, UserNote, Warning
from database.models.module import ModuleConfig
from database.models.permissions import (
    DashboardGuildAccess,
    DashboardUser,
    InstanceAccess,
    InstanceInvite,
    ModuleRoleAccess,
)
from database.models.reputation import (
    ReputationAward,
    ReputationEvent,
    ReputationProfile,
    ReputationReward,
    ReputationTier,
)
from database.models.role_manager import RoleAssignment, RoleRule
from database.models.ruleset import Rule, RuleSet, WordList
from database.models.voice import VoiceSession

__all__ = [
    "ActivitySnapshot",
    "AuditLog",
    "AutoModConfig",
    "AutoVoiceChannel",
    "DailyChannelStat",
    "DailyEmojiStat",
    "DashboardGuildAccess",
    "DashboardUser",
    "FileAttachment",
    "Guild",
    "GuildSetting",
    "InstanceAccess",
    "InstanceInvite",
    "LogConfig",
    "ModerationCase",
    "ModuleConfig",
    "ModuleRoleAccess",
    "ReputationAward",
    "ReputationEvent",
    "ReputationProfile",
    "ReputationReward",
    "ReputationTier",
    "RoleAssignment",
    "RoleRule",
    "Rule",
    "RuleSet",
    "UserNote",
    "VoiceSession",
    "Warning",
    "WordList",
]
