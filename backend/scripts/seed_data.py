import asyncio
import os
import sys

sys.path.append(os.getcwd())

from sqlmodel import select
from app.core.database import async_session_maker
from app.models.user import User
from app.models.order import Order, OrderStatus


async def ensure_user(session, username: str, password: str, email: str, full_name: str, phone: str | None = None) -> User:
    result = await session.exec(select(User).where(User.username == username))
    user = result.first()

    if user:
        return user

    print(f"Creating user {username}...")
    user = User(
        username=username,
        password_hash=User.hash_password(password),
        email=email,
        full_name=full_name,
        phone=phone,
    )
    session.add(user)
    await session.flush()
    return user



async def seed_data():
    async with async_session_maker() as session:
        test_user = await ensure_user(session, "test_user", "test123", "test@example.com", "张三", "13800138000")
        alice = await ensure_user(session, "alice", "alice123", "alice@example.com", "Alice Wang", "13800138001")
        bob = await ensure_user(session, "bob", "bob123", "bob@example.com", "Bob Chen", "13800138002")

        order_specs = [
            Order(
                order_sn="SN20241001",
                user_id=test_user.id,
                status=OrderStatus.SHIPPED,
                total_amount=128.50,
                items=[{"name": "运动内衣", "qty": 1, "price": 128.50}],
                tracking_number="SF123456789",
                shipping_address="上海市浦东新区张江高科技园区",
            ),
            Order(
                order_sn="SN20241002",
                user_id=test_user.id,
                status=OrderStatus.PENDING,
                total_amount=50.00,
                items=[{"name": "全棉袜子", "qty": 5, "price": 10.00}],
                shipping_address="北京市朝阳区三里屯",
            ),
            Order(
                order_sn="SN20241003",
                user_id=test_user.id,
                status=OrderStatus.SHIPPED,
                total_amount=199.00,
                items=[
                    {"name": "运动T恤", "qty": 1, "price": 99.00},
                    {"name": "运动短裤", "qty": 1, "price": 100.00},
                ],
                tracking_number="SF987654321",
                shipping_address="上海市浦东新区张江高科技园区",
            ),
            Order(
                order_sn="SN20241004",
                user_id=test_user.id,
                status=OrderStatus.DELIVERED,
                total_amount=599.00,
                items=[{"name": "耐克篮球鞋", "qty": 1, "price": 599.00}],
                tracking_number="SF555666777",
                shipping_address="北京市海淀区中关村",
            ),
            Order(
                order_sn="SN20241005",
                user_id=alice.id,
                status=OrderStatus.DELIVERED,
                total_amount=329.00,
                items=[{"name": "轻量跑步鞋", "qty": 1, "price": 329.00}],
                tracking_number="SF111222333",
                shipping_address="上海市徐汇区漕溪北路",
            ),
            Order(
                order_sn="SN20241006",
                user_id=bob.id,
                status=OrderStatus.SHIPPED,
                total_amount=88.00,
                items=[{"name": "户外遮阳帽", "qty": 2, "price": 44.00}],
                tracking_number="SF444555666",
                shipping_address="杭州市西湖区文三路",
            ),
        ]

        created = 0
        for order in order_specs:
            existing = await session.exec(select(Order).where(Order.order_sn == order.order_sn))
            if existing.first():
                continue
            session.add(order)
            created += 1

        await session.commit()
        print(f"Seed data completed. Created {created} orders.")


if __name__ == "__main__":
    asyncio.run(seed_data())
