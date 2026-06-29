"""
AutoMod configuration model.
"""

from sqlalchemy import String, Integer, Boolean, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.engine import Base


class AutoModConfig(Base):
    __tablename__ = "automod_configs"
    __table_args__ = (UniqueConstraint("guild_id", "rule_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(Integer, ForeignKey("guilds.id"), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(32), nullable=False)  # spam/invite/mention
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    action: Mapped[str] = mapped_column(String(16), nullable=False, default="warn")  # warn/timeout/delete
    duration: Mapped[int] = mapped_column(Integer, nullable=False, default=10)  # minutes
    ignored_roles: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON array
    ignored_channels: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON array

    guild = relationship("Guild", back_populates="automod_configs")

    def __repr__(self) -> str:
        return f"<AutoModConfig guild_id={self.guild_id} rule='{self.rule_type}' enabled={self.enabled}>"
