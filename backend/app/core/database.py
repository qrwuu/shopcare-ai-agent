# app/core/database.py
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
from typing import AsyncGenerator
from sqlalchemy import text
from sqlmodel import SQLModel

# Import every ORM model before metadata.create_all; fresh databases used to fail
# because custom chat tables referenced users before users had been created.
import app.models  # noqa: F401
from app.models.attachment import Attachment  # noqa: F401
from app.models.notification import Notification  # noqa: F401

# 1. 创建异步引擎
# echo=True 会打印 SQL 日志，方便调试，生产环境请关掉
engine = create_async_engine(settings.DATABASE_URL, echo=False, future=True)

# 2. 创建 Session 工厂
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

# 3. FastAPI 依赖注入函数 (Dependency)
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session

# 4. 初始化 DB 工具 (用于创建 pgvector 扩展)
async def init_db():
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(SQLModel.metadata.create_all)
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                thread_id VARCHAR(128) NOT NULL,
                title VARCHAR(32) NOT NULL DEFAULT '新的咨询',
                order_sn VARCHAR(32),
                is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
                meta_data JSON DEFAULT '{}'::json,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, thread_id)
            )
        """))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_chat_sessions_user_updated ON chat_sessions(user_id, updated_at DESC)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_chat_sessions_order_sn ON chat_sessions(order_sn)"))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                thread_id VARCHAR(128) NOT NULL,
                role VARCHAR(24) NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                message_type VARCHAR(32) NOT NULL DEFAULT 'text',
                order_sn VARCHAR(32),
                card_data JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_chat_messages_user_thread_created ON chat_messages(user_id, thread_id, created_at)"))

        await conn.execute(text("ALTER TABLE refund_applications ADD COLUMN IF NOT EXISTS stage VARCHAR"))
        await conn.execute(text("ALTER TABLE refund_applications ADD COLUMN IF NOT EXISTS return_tracking_number VARCHAR"))
        await conn.execute(text("ALTER TABLE refund_applications ADD COLUMN IF NOT EXISTS timeline TEXT"))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS attachments (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                thread_id VARCHAR(128) NOT NULL,
                order_sn VARCHAR(32),
                refund_application_id INTEGER,
                attachment_type VARCHAR(32) NOT NULL DEFAULT 'image',
                filename VARCHAR(255) NOT NULL,
                content_type VARCHAR(128) NOT NULL DEFAULT 'application/octet-stream',
                url VARCHAR(512) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_attachments_user_thread ON attachments(user_id, thread_id, created_at)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_attachments_order_sn ON attachments(order_sn)"))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS notifications (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title VARCHAR(80) NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                target_type VARCHAR(32) NOT NULL DEFAULT 'after_sales',
                target_id VARCHAR(128),
                is_read BOOLEAN NOT NULL DEFAULT FALSE,
                meta_data JSON DEFAULT '{}'::json,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_notifications_user_read_created ON notifications(user_id, is_read, created_at DESC)"))
