"""消费者端未读通知。"""
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import Column, String, Text, JSON, text
from sqlmodel import SQLModel, Field


class Notification(SQLModel, table=True):
    __tablename__ = "notifications"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="users.id", ondelete="CASCADE")
    title: str = Field(sa_column=Column(String(80), nullable=False))
    content: str = Field(default="", sa_column=Column(Text, nullable=False))
    target_type: str = Field(default="after_sales", sa_column=Column(String(32), index=True, nullable=False))
    target_id: Optional[str] = Field(default=None, index=True, max_length=128)
    is_read: bool = Field(default=False, index=True)
    meta_data: dict = Field(default={}, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None), sa_column_kwargs={"server_default": text("CURRENT_TIMESTAMP")})
