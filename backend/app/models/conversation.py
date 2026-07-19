"""消费者聊天历史会话。"""
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from sqlalchemy import Column, String, Text, JSON, text
from sqlmodel import SQLModel, Field


class ChatSession(SQLModel, table=True):
    __tablename__ = "chat_sessions"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="users.id", ondelete="CASCADE")
    thread_id: str = Field(index=True, max_length=128)
    title: str = Field(default="新的咨询", max_length=32)
    order_sn: Optional[str] = Field(default=None, index=True, max_length=32)
    is_deleted: bool = Field(default=False, index=True)
    meta_data: Dict[str, Any] = Field(default={}, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None), sa_column_kwargs={"server_default": text("CURRENT_TIMESTAMP")})
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None), sa_column_kwargs={"server_default": text("CURRENT_TIMESTAMP"), "onupdate": text("CURRENT_TIMESTAMP")})


class ChatMessage(SQLModel, table=True):
    __tablename__ = "chat_messages"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="users.id", ondelete="CASCADE")
    thread_id: str = Field(index=True, max_length=128)
    role: str = Field(sa_column=Column(String(24), index=True, nullable=False))
    content: str = Field(default="", sa_column=Column(Text, nullable=False))
    message_type: str = Field(default="text", sa_column=Column(String(32), index=True, nullable=False))
    order_sn: Optional[str] = Field(default=None, index=True, max_length=32)
    card_data: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None), sa_column_kwargs={"server_default": text("CURRENT_TIMESTAMP")})
