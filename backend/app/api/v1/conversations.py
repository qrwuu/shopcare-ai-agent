"""消费者历史会话 API。"""
from datetime import datetime
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import select
from sqlalchemy import exists

from app.core.database import async_session_maker
from app.core.security import get_current_user_id
from app.models.conversation import ChatSession, ChatMessage
from app.models.order import Order
from app.services.conversation_service import get_or_create_session, add_message, order_card_data, now_naive

router = APIRouter()

STATUS_LABELS = {
    "PENDING": "待付款",
    "PAID": "待发货",
    "SHIPPED": "运输中",
    "INTERCEPTING": "拦截中",
    "DELIVERED": "已签收",
    "REFUNDING": "退款处理中",
    "REFUNDED": "已退款",
    "CANCELLED": "已取消",
}

class ChatSessionCreate(BaseModel):
    thread_id: str

class ChatSessionPatch(BaseModel):
    order_sn: Optional[str] = None
    title: Optional[str] = None
    add_order_card: bool = False

class ChatSessionResponse(BaseModel):
    thread_id: str
    title: str
    order_sn: Optional[str]
    created_at: str
    updated_at: str

class ChatMessageResponse(BaseModel):
    id: int
    role: str
    content: str
    message_type: str
    order_sn: Optional[str]
    card_data: Optional[dict[str, Any]]
    created_at: str

class ChatSessionDetail(ChatSessionResponse):
    messages: List[ChatMessageResponse]


def _time(value: datetime) -> str:
    return value.isoformat()


def _status_value(value: object) -> str:
    return getattr(value, "value", value) or ""


def _session_response(session: ChatSession) -> ChatSessionResponse:
    return ChatSessionResponse(
        thread_id=session.thread_id,
        title=session.title,
        order_sn=session.order_sn,
        created_at=_time(session.created_at),
        updated_at=_time(session.updated_at),
    )


def _message_response(message: ChatMessage) -> ChatMessageResponse:
    data = dict(message.card_data or {}) if message.card_data else None
    if data and data.get("status"):
        data["status_label"] = STATUS_LABELS.get(str(data["status"]), str(data["status"]))
    return ChatMessageResponse(
        id=message.id or 0,
        role=message.role,
        content=message.content,
        message_type=message.message_type,
        order_sn=message.order_sn,
        card_data=data,
        created_at=_time(message.created_at),
    )


@router.get("/customer/chat-sessions", response_model=List[ChatSessionResponse])
async def list_chat_sessions(current_user_id: int = Depends(get_current_user_id)):
    async with async_session_maker() as session:
        has_user_message = exists().where(
            ChatMessage.user_id == ChatSession.user_id,
            ChatMessage.thread_id == ChatSession.thread_id,
            ChatMessage.role == "user",
            ChatMessage.content != "",
        )
        result = await session.exec(
            select(ChatSession)
            .where(
                ChatSession.user_id == current_user_id,
                ChatSession.is_deleted == False,  # noqa: E712
                ChatSession.title != "新的咨询",
                has_user_message,
            )
            .order_by(ChatSession.updated_at.desc())
        )
        return [_session_response(item) for item in result.all()]


@router.post("/customer/chat-sessions", response_model=ChatSessionResponse)
async def create_chat_session(request: ChatSessionCreate, current_user_id: int = Depends(get_current_user_id)):
    async with async_session_maker() as session:
        chat_session = await get_or_create_session(session, current_user_id, request.thread_id)
        await session.commit()
        await session.refresh(chat_session)
        return _session_response(chat_session)


@router.get("/customer/chat-sessions/{thread_id}", response_model=ChatSessionDetail)
async def get_chat_session(thread_id: str, current_user_id: int = Depends(get_current_user_id)):
    async with async_session_maker() as session:
        result = await session.exec(select(ChatSession).where(ChatSession.user_id == current_user_id, ChatSession.thread_id == thread_id, ChatSession.is_deleted == False))  # noqa: E501,E712
        chat_session = result.first()
        if not chat_session:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
        msg_result = await session.exec(select(ChatMessage).where(ChatMessage.user_id == current_user_id, ChatMessage.thread_id == thread_id).order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc()))
        return ChatSessionDetail(**_session_response(chat_session).model_dump(), messages=[_message_response(item) for item in msg_result.all()])


@router.patch("/customer/chat-sessions/{thread_id}", response_model=ChatSessionResponse)
async def update_chat_session(thread_id: str, request: ChatSessionPatch, current_user_id: int = Depends(get_current_user_id)):
    async with async_session_maker() as session:
        chat_session = await get_or_create_session(session, current_user_id, thread_id, request.order_sn)
        if request.title:
            chat_session.title = request.title[:14]
        order = None
        if request.order_sn:
            result = await session.exec(select(Order).where(Order.user_id == current_user_id, Order.order_sn == request.order_sn.upper()))
            order = result.first()
            if not order:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到该订单")
            chat_session.order_sn = order.order_sn
        chat_session.updated_at = now_naive()
        session.add(chat_session)
        if request.add_order_card and order:
            await add_message(session, current_user_id, thread_id, "system", message_type="order_card", order_sn=order.order_sn, card_data=order_card_data(order))
        await session.commit()
        await session.refresh(chat_session)
        return _session_response(chat_session)


@router.delete("/customer/chat-sessions/{thread_id}", status_code=204)
async def delete_chat_session(thread_id: str, current_user_id: int = Depends(get_current_user_id)):
    async with async_session_maker() as session:
        result = await session.exec(select(ChatSession).where(ChatSession.user_id == current_user_id, ChatSession.thread_id == thread_id))
        chat_session = result.first()
        if chat_session:
            chat_session.is_deleted = True
            chat_session.updated_at = now_naive()
            session.add(chat_session)
            await session.commit()
