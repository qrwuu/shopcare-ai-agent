"""体验订单与内置账号初始化。"""
from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.order import Order, OrderStatus
from app.models.refund import RefundApplication, RefundReason, RefundStatus
from app.models.user import User

ADMIN_ACCOUNT = "80000001"
ADMIN_PASSWORD = "123456"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _item(name: str, price: float, image: str, **attrs: str) -> dict:
    data = {"name": name, "qty": 1, "price": price, "image_url": image}
    data.update({key: value for key, value in attrs.items() if value})
    return data


async def ensure_admin_account(session: AsyncSession) -> User:
    result = await session.exec(select(User).where(User.username == ADMIN_ACCOUNT))
    user = result.first()
    if user:
        if not user.is_admin:
            user.is_admin = True
            session.add(user)
        return user

    user = User(
        username=ADMIN_ACCOUNT,
        password_hash=User.hash_password(ADMIN_PASSWORD),
        email="admin80000001@shopcare.local",
        full_name="售后审核员",
        is_admin=True,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


def _order_specs(user_id: int, prefix: str) -> Iterable[Order]:
    now = _now()
    return [
        Order(
            order_sn=f"{prefix}01",
            user_id=user_id,
            status=OrderStatus.PAID,
            total_amount=129.00,
            items=[_item("云柔家居服套装", 129.00, "https://images.unsplash.com/photo-1523381294911-8d3cead13475?auto=format&fit=crop&w=240&q=80", material="棉感针织面料", color="浅绿", spec="套装", size="M")],
            tracking_number=None,
            shipping_address="上海市浦东新区世纪大道 100 号",
            created_at=now - timedelta(hours=6),
        ),
        Order(
            order_sn=f"{prefix}02",
            user_id=user_id,
            status=OrderStatus.SHIPPED,
            total_amount=88.00,
            items=[_item("便携保温杯", 88.00, "https://images.unsplash.com/photo-1523362628745-0c100150b504?auto=format&fit=crop&w=240&q=80", material="食品接触级不锈钢", capacity="500ml", color="米白")],
            tracking_number=f"SF{prefix[-6:]}02",
            shipping_address="上海市浦东新区世纪大道 100 号",
            created_at=now - timedelta(days=2),
        ),
        Order(
            order_sn=f"{prefix}03",
            user_id=user_id,
            status=OrderStatus.DELIVERED,
            total_amount=159.00,
            items=[_item("轻量通勤双肩包", 159.00, "https://images.unsplash.com/photo-1553062407-98eeb64c6a62?auto=format&fit=crop&w=240&q=80", material="耐磨织物", capacity="18L", color="黑色")],
            tracking_number=f"SF{prefix[-6:]}03",
            shipping_address="上海市浦东新区世纪大道 100 号",
            created_at=now - timedelta(days=3),
        ),
        Order(
            order_sn=f"{prefix}04",
            user_id=user_id,
            status=OrderStatus.DELIVERED,
            total_amount=899.00,
            items=[_item("智能降噪耳机 Pro", 899.00, "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?auto=format&fit=crop&w=240&q=80", spec="主动降噪版", color="白色")],
            tracking_number=f"SF{prefix[-6:]}04",
            shipping_address="上海市浦东新区世纪大道 100 号",
            created_at=now - timedelta(days=16),
        ),
        Order(
            order_sn=f"{prefix}05",
            user_id=user_id,
            status=OrderStatus.DELIVERED,
            total_amount=66.00,
            items=[_item("香氛洗护旅行套装", 66.00, "https://images.unsplash.com/photo-1556228578-8c89e6adf883?auto=format&fit=crop&w=240&q=80", spec="旅行装", scent="清爽花果香")],
            tracking_number=f"SF{prefix[-6:]}05",
            shipping_address="上海市浦东新区世纪大道 100 号",
            created_at=now - timedelta(days=5),
        ),
    ]


async def ensure_demo_orders_for_user(session: AsyncSession, user: User, reset: bool = False) -> None:
    if user.id is None:
        return

    prefix = f"SC{user.username[-6:]}"
    if reset:
        existing = await session.exec(select(RefundApplication).where(RefundApplication.user_id == user.id))
        for refund in existing.all():
            await session.delete(refund)

        existing_orders = await session.exec(select(Order).where(Order.user_id == user.id, Order.order_sn.startswith(prefix)))
        for order in existing_orders.all():
            await session.delete(order)
        await session.flush()

    existing_count = await session.exec(select(Order).where(Order.user_id == user.id))
    if existing_count.first() and not reset:
        return

    created_orders: list[Order] = []
    for order in _order_specs(user.id, prefix):
        exists = await session.exec(select(Order).where(Order.order_sn == order.order_sn))
        if exists.first():
            continue
        session.add(order)
        created_orders.append(order)

    await session.flush()

    completed_order = next((order for order in created_orders if order.order_sn.endswith("05")), None)
    if completed_order and completed_order.id:
        refund = RefundApplication(
            order_id=completed_order.id,
            user_id=user.id,
            status=RefundStatus.COMPLETED,
            reason_category=RefundReason.OTHER,
            reason_detail="体验数据：售后已完成",
            refund_amount=float(completed_order.total_amount),
            admin_note="退款已原路退回。",
            reviewed_at=_now() - timedelta(days=1),
            created_at=_now() - timedelta(days=2),
        )
        session.add(refund)
