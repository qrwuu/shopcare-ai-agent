# app/api/v1/schemas.py
from typing import Optional
from pydantic import BaseModel, Field

class ChatRequest(BaseModel):
    # 用户的问题
    question: str = Field(..., example="内衣拆封了可以退吗？")

    # 会话 ID，用于后续追踪对话上下文 (v1.0 暂不强制，但预留)
    thread_id: str = Field("default_thread", example="user_123_session_001")

    # 前端订单选择绑定，仅用于内部上下文，不直接展示给消费者。
    order_sn: Optional[str] = Field(default=None, example="SN20241004")

class ChatResponse(BaseModel):
    # 非流式模式下的返回结构
    answer: str