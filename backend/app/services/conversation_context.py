"""Build a bounded, consumer-safe conversation window for Agent prompts."""
from __future__ import annotations

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.conversation import ChatMessage


async def recent_conversation_context(
    session: AsyncSession,
    user_id: int,
    thread_id: str,
    limit: int = 10,
    per_message_limit: int = 420,
) -> str:
    """Return the latest user/assistant turns in chronological order.

    The database is the source of truth.  This avoids relying on browser state or
    a single previous assistant reply when resolving pronouns such as “那个” or
    “按刚才说的”。  Card/system events are intentionally excluded from prompts.
    """
    result = await session.exec(
        select(ChatMessage)
        .where(
            ChatMessage.user_id == user_id,
            ChatMessage.thread_id == thread_id,
            ChatMessage.role.in_(["user", "assistant"]),
            ChatMessage.content != "",
        )
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(limit)
    )
    messages = list(reversed(result.all()))
    lines: list[str] = []
    for message in messages:
        content = " ".join((message.content or "").split())
        if not content:
            continue
        if len(content) > per_message_limit:
            content = content[:per_message_limit].rstrip() + "…"
        speaker = "用户" if message.role == "user" else "客服"
        lines.append(f"{speaker}：{content}")
    return "\n".join(lines)
