"""消费者聊天会话持久化。"""
from datetime import datetime, timezone
import re
import json
from typing import Any, Optional
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.conversation import ChatSession, ChatMessage
from app.models.order import Order

GREETINGS = {"你好", "您好", "在吗", "hello", "hi", "哈喽", "喂"}


def now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def is_effective_question(text: str) -> bool:
    cleaned = re.sub(r"[\s，。！？!?.~～]+", "", text).lower()
    return bool(cleaned) and cleaned not in GREETINGS and len(cleaned) >= 3


def generate_title(text: str) -> str:
    if any(k in text for k in ["改地址", "修改地址", "收货地址", "地址"]):
        return "修改订单地址"
    if any(k in text for k in ["物流", "快递", "到哪", "催发货"]):
        return "查询物流进度"
    if any(k in text for k in ["退货退款", "退货", "退款", "售后"]):
        return "申请退货退款"
    if any(k in text for k in ["换货", "换一个"]):
        return "申请商品换货"
    if any(k in text for k in ["发票", "抬头", "税号"]):
        return "咨询发票问题"
    if any(k in text for k in ["优惠券", "券", "优惠码"]):
        return "咨询优惠券"
    if any(k in text for k in ["订单", "买的"]):
        return "查询订单信息"
    cleaned = re.sub(r"[^一-龥A-Za-z0-9]", "", text)
    return (cleaned[:14] or "售后咨询")[:14]


async def get_or_create_session(session: AsyncSession, user_id: int, thread_id: str, order_sn: Optional[str] = None) -> ChatSession:
    result = await session.exec(select(ChatSession).where(ChatSession.user_id == user_id, ChatSession.thread_id == thread_id))
    chat_session = result.first()
    if chat_session:
        chat_session.is_deleted = False
        if order_sn:
            chat_session.order_sn = order_sn
        chat_session.updated_at = now_naive()
        session.add(chat_session)
        return chat_session

    chat_session = ChatSession(user_id=user_id, thread_id=thread_id, order_sn=order_sn, updated_at=now_naive())
    session.add(chat_session)
    await session.flush()
    return chat_session


async def ensure_title(session: AsyncSession, chat_session: ChatSession, text: str) -> None:
    if chat_session.title != "新的咨询":
        return
    if not is_effective_question(text):
        return
    chat_session.title = generate_title(text)
    chat_session.updated_at = now_naive()
    session.add(chat_session)


async def add_message(
    session: AsyncSession,
    user_id: int,
    thread_id: str,
    role: str,
    content: str = "",
    message_type: str = "text",
    order_sn: Optional[str] = None,
    card_data: Optional[dict[str, Any]] = None,
) -> ChatMessage:
    message = ChatMessage(
        user_id=user_id,
        thread_id=thread_id,
        role=role,
        content=content or "",
        message_type=message_type,
        order_sn=order_sn,
        card_data=card_data,
    )
    session.add(message)
    return message


def remember_product_catalog(chat_session: ChatSession, content: str) -> None:
    """Persist the latest product cards so “第二个/刚才那款” has a stable referent."""
    match = re.search(r"\[\[PRODUCT_CARDS:(.*?)\]\]", content or "", re.S)
    if not match:
        return
    try:
        payload = json.loads(match.group(1))
        items = payload.get("items", []) if isinstance(payload, dict) else payload
    except (TypeError, ValueError, json.JSONDecodeError):
        return
    if not isinstance(items, list):
        return
    allowed_keys = {
        "id", "name", "price", "colors", "sizes", "stock_status", "selling_points", "category",
        "demo_generated", "source", "inventory_by_color", "inventory_by_size",
        "restock_eta_by_color", "restock_eta_by_size",
    }
    sanitized = [{key: item.get(key) for key in allowed_keys if key in item} for item in items if isinstance(item, dict) and item.get("name")]
    if not sanitized:
        return
    meta = dict(chat_session.meta_data or {})
    meta["last_catalog"] = {"items": sanitized, "updated_at": now_naive().isoformat()}
    chat_session.meta_data = meta
    chat_session.updated_at = now_naive()

def order_card_data(order: Order) -> dict[str, Any]:
    item = (order.items or [{}])[0] if isinstance(order.items, list) else {}
    return {
        "id": order.id,
        "order_sn": order.order_sn,
        "product_name": item.get("name") or "订单商品",
        "product_image": item.get("image_url") or item.get("image"),
        "total_amount": float(order.total_amount),
        "status": getattr(order.status, "value", order.status),
        "shipping_address": order.shipping_address,
        "tracking_number": order.tracking_number,
        "created_at": order.created_at.isoformat(),
    }
