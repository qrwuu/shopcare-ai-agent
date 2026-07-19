"""消费者上传的图片与售后凭证。"""
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import Column, String, text
from sqlmodel import SQLModel, Field


class Attachment(SQLModel, table=True):
    __tablename__ = "attachments"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="users.id", ondelete="CASCADE")
    thread_id: str = Field(index=True, max_length=128)
    order_sn: Optional[str] = Field(default=None, index=True, max_length=32)
    refund_application_id: Optional[int] = Field(default=None, index=True)
    attachment_type: str = Field(default="image", sa_column=Column(String(32), index=True, nullable=False))
    filename: str = Field(sa_column=Column(String(255), nullable=False))
    content_type: str = Field(default="application/octet-stream", sa_column=Column(String(128), nullable=False))
    url: str = Field(sa_column=Column(String(512), nullable=False))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None), sa_column_kwargs={"server_default": text("CURRENT_TIMESTAMP")})
