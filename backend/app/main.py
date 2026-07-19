# app/main.py
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.chat import router as chat_router
from app.api.v1.status import router as status_router
from app.api.v1.admin import router as admin_router
from app.api.v1.websocket import router as websocket_router
from app.api.v1.auth import router as auth_router  # v4.0 新增
from app.api.v1.customer import router as customer_router
from app.api.v1.conversations import router as conversations_router
from app.core.config import settings
from app.core.database import init_db, async_session_maker
from app.services.demo_data import ensure_admin_account
from app.graph.workflow import compile_app_graph
import app.graph.workflow as workflow_module
from pathlib import Path

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="4.0.0",
    description="全栈·沉浸式人机协作系统 (The Immersive System) - v4.0"
)

# 1. 配置跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# 2. 注册路由
app.include_router(auth_router, prefix=settings.API_V1_STR, tags=["Auth"])  # v4.0 新增
app.include_router(customer_router, prefix=settings.API_V1_STR, tags=["Customer"])
app.include_router(conversations_router, prefix=settings.API_V1_STR, tags=["Conversations"])
app.include_router(chat_router, prefix=settings.API_V1_STR, tags=["Chat"])
app.include_router(status_router, prefix=settings.API_V1_STR, tags=["Status"])
app.include_router(admin_router, prefix=settings.API_V1_STR, tags=["Admin"])
app.include_router(websocket_router, prefix=settings.API_V1_STR, tags=["WebSocket"])

UPLOAD_DIR = Path(__file__).resolve().parents[1] / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")


@app.on_event("startup")
async def on_startup():
    print(" Starting E-commerce Smart Agent v4.0...")
    await init_db()
    async with async_session_maker() as session:
        await ensure_admin_account(session)
        await session.commit()
    workflow_module.app_graph = await compile_app_graph()
    print(" Infrastructure is ready.")


@app.get("/")
async def root():
    return {
        "service": settings.PROJECT_NAME,
        "status": "running",
        "docs": "/docs",
        "health": "/health",
        "frontend": "http://localhost:3000",
        "gradio_customer": "http://localhost:7860",
        "gradio_admin": "http://localhost:7861",
    }


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "version": "v4.0",
        "features": [
            "用户登录认证",
            "多租户数据隔离",
            "订单查询",
            "政策咨询",
            "退货申请",
            "人工审核",
            "实时状态同步",
            "管理员工作台"
        ],
        "eval_mode": settings.AGENT_EVAL_MODE and settings.EVAL_ISOLATED,
    }