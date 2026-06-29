"""
File attachment tracking model.

Logs every file uploaded to the server for audit purposes.
"""

from datetime import datetime, timezone

from sqlalchemy import String, Integer, BigInteger, DateTime, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.engine import Base


class FileAttachment(Base):
    __tablename__ = "file_attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(Integer, ForeignKey("guilds.id"), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False)
    message_id: Mapped[str] = mapped_column(String(32), nullable=False)
    author_id: Mapped[str] = mapped_column(String(32), nullable=False)
    author_tag: Mapped[str] = mapped_column(String(64), nullable=False, default="Unknown#0000")
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    file_url: Mapped[str] = mapped_column(Text, nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False, default="application/octet-stream")
    is_image: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    guild = relationship("Guild")

    def __repr__(self) -> str:
        return f"<FileAttachment id={self.id} file='{self.filename}' size={self.file_size}>"
