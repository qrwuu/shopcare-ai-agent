"""Single consumer-chat orchestration: plan with an LLM, execute with trusted services."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from sqlmodel import select

from app.core.database import async_session_maker
from app.models.attachment import Attachment
from app.models.conversation import ChatSession
from app.models.order import Order
from app.models.refund import RefundApplication
from app.services.conversation_context import recent_conversation_context
from app.services.conversation_service import get_or_create_session, now_naive
from app.services.agent_telemetry import invoke_llm

ALLOWED_INTENTS = {
    "general", "clarify", "product_question", "product_recommendation", "order_query",
    "logistics", "urge_shipping", "modify_address", "cancel_order", "return_refund",
    "refund_only", "exchange", "damaged_or_missing", "after_sales_status",
    "cancel_after_sales", "coupon", "payment", "invoice", "price_negotiation", "human",
}

INTENT_TO_EXECUTOR = {
    "product_question": "product_detail",
    "product_recommendation": "presales",
}


@dataclass
class AgentPlan:
    intent: str
    confidence: float
    needs_clarification: bool
    clarification: str
    facts: list[str]
    requested_fields: list[str]

    @property
    def executor_intent(self) -> str:
        return INTENT_TO_EXECUTOR.get(self.intent, self.intent)


def _strip_json(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I)
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return None
    try:
        value = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _bounded_strings(value: object, limit: int = 4) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip()[:120] for item in value if str(item).strip()][:limit]


def _order_snapshot(order: Optional[Order]) -> dict[str, Any]:
    if not order:
        return {}
    return {
        "order_sn": order.order_sn,
        "status": str(getattr(order.status, "value", order.status)),
        "amount": float(order.total_amount),
        "items": order.items or [],
        "tracking_number": order.tracking_number,
        "shipping_address": order.shipping_address,
    }


async def _load_facts(user_id: int, thread_id: str, requested_order_sn: Optional[str]) -> tuple[ChatSession, Optional[Order], list[Attachment], str]:
    async with async_session_maker() as session:
        chat = await get_or_create_session(session, user_id, thread_id, requested_order_sn)
        effective_sn = requested_order_sn or chat.order_sn
        order = None
        if effective_sn:
            result = await session.exec(select(Order).where(Order.user_id == user_id, Order.order_sn == effective_sn.upper()))
            order = result.first()
            if order and chat.order_sn != order.order_sn:
                chat.order_sn = order.order_sn
        attachments = list((await session.exec(
            select(Attachment)
            .where(Attachment.user_id == user_id, Attachment.thread_id == thread_id)
            .order_by(Attachment.created_at.desc())
            .limit(6)
        )).all())
        history = await recent_conversation_context(session, user_id, thread_id)
        await session.commit()
        return chat, order, list(reversed(attachments)), history


async def plan_customer_message(user_id: int, thread_id: str, question: str, order_sn: Optional[str]) -> tuple[AgentPlan, Optional[Order], list[Attachment], str]:
    """Return a bounded structured plan. Failure falls back to safe legacy routing."""
    chat, order, attachments, history = await _load_facts(user_id, thread_id, order_sn)
    state = dict(chat.meta_data or {}).get("agent_state") or {}
    attachment_facts = [
        {"id": item.id, "type": item.attachment_type, "filename": item.filename, "order_sn": item.order_sn}
        for item in attachments
    ]
    prompt = """你是电商客服 Agent 的规划器，不直接执行退款、改地址、取消订单等操作。
只输出一个 JSON 对象，字段严格为：
{"intent":"...","confidence":0-1,"needs_clarification":true/false,"clarification":"...","facts":["..."],"requested_fields":["..."]}
intent 只能是：general, clarify, product_question, product_recommendation, order_query, logistics, urge_shipping, modify_address, cancel_order, return_refund, refund_only, exchange, damaged_or_missing, after_sales_status, cancel_after_sales, coupon, payment, invoice, price_negotiation, human。

原则：
- 优先理解用户真实诉求和代词，不要只按单个关键词分类。
- 信息不足且可能对应多个处理方向时，intent=clarify，提出一个简短、具体的问题；不得自行猜成价格、退款或投诉。
- “换成黑色/换小一码/颜色不对”通常是 exchange；“质量扎人、破损、漏液、错发、少件”通常是 damaged_or_missing。
- 用户明确说“我要投诉”或“转人工”时，intent=human；不得因为缺少细节把明确的人工诉求改写成泛泛追问。
- 其他用户的订单、地址、电话等隐私请求只能拒绝，不得查询、展示或承诺代办。
- 订单/库存/图片内容未被事实资料证实时，不得编造。
- 仅在意图明确且有事实支持时给高置信度。
"""
    if os.getenv("AGENT_PROMPT_VARIANT", "A").upper() == "B":
        prompt += """
Decision protocol:
1. Resolve pronouns and short replies from pending state, recent dialogue and current order before classifying.
2. Apply negation and intent switching first; never keep a negated refund or cancellation intent.
3. For multiple intents containing a critical action, ask which action to handle first. Never execute without explicit confirmation.
4. Ground product, inventory, order and policy claims only in supplied facts. Ask only for the minimum missing field.
5. A short confirmation confirms only an existing pending action; an orphan confirmation must be clarified.
6. Ask one specific, actionable clarification question and avoid generic scope scripts.
"""
    payload = {
        "当前会话状态": state,
        "当前订单": _order_snapshot(order),
        "最近附件（仅文件元数据，尚未做视觉识别）": attachment_facts,
        "最近对话": history or "无",
        "用户最新消息": question,
    }
    parsed: dict[str, Any] | None = None
    try:
        from app.graph.nodes import llm
        response = await invoke_llm(llm, [
            SystemMessage(content=prompt),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
        ], stage="planner")
        parsed = _strip_json(str(getattr(response, "content", "") or ""))
    except Exception:
        parsed = None

    if not parsed:
        from app.services.agent_service import classify_intent
        legacy = classify_intent(question)
        intent = "product_question" if legacy in {"product", "product_detail"} else legacy
        plan = AgentPlan(intent=intent if intent in ALLOWED_INTENTS else "general", confidence=0.35, needs_clarification=False, clarification="", facts=[], requested_fields=[])
    else:
        intent = str(parsed.get("intent") or "clarify").strip()
        confidence = float(parsed.get("confidence") or 0)
        plan = AgentPlan(
            intent=intent if intent in ALLOWED_INTENTS else "clarify",
            confidence=max(0.0, min(1.0, confidence)),
            needs_clarification=bool(parsed.get("needs_clarification")) or intent == "clarify" or confidence < 0.45,
            clarification=str(parsed.get("clarification") or "").strip()[:240],
            facts=_bounded_strings(parsed.get("facts")),
            requested_fields=_bounded_strings(parsed.get("requested_fields")),
        )

    async with async_session_maker() as session:
        stored = await get_or_create_session(session, user_id, thread_id, order.order_sn if order else order_sn)
        meta = dict(stored.meta_data or {})
        meta["agent_state"] = {
            "last_intent": plan.intent,
            "last_facts": plan.facts,
            "requested_fields": plan.requested_fields,
            "last_order_sn": order.order_sn if order else stored.order_sn,
            "attachment_ids": [item.id for item in attachments if item.id],
            "updated_at": now_naive().isoformat(),
        }
        stored.meta_data = meta
        stored.updated_at = now_naive()
        session.add(stored)
        await session.commit()

    return plan, order, attachments, history


def clarification_reply(plan: AgentPlan) -> str:
    if plan.clarification:
        return plan.clarification
    if plan.requested_fields:
        return "为了不误处理，我还需要确认一下：" + "、".join(plan.requested_fields) + "。"
    return "我想先确认一下：你希望处理的是商品本身、订单物流，还是售后/退款？"

async def grounded_fallback_reply(plan: AgentPlan, order: Optional[Order], attachments: list[Attachment], history: str, question: str) -> str:
    """Natural-language fallback that is grounded in the same facts as planning."""
    facts = {
        "plan": {"intent": plan.intent, "facts": plan.facts, "requested_fields": plan.requested_fields},
        "order": _order_snapshot(order),
        "attachments": [{"type": item.attachment_type, "filename": item.filename} for item in attachments],
        "history": history,
    }
    prompt = """你是店小服。基于给定事实自然回答用户最新消息。
不要编造订单、库存、活动、图片内容或政策；信息不足时说明下一步核实方式。不要展示内部计划、工具、数据库或技术名词。若用户表达模糊，先问一个具体澄清问题。"""
    if os.getenv("AGENT_PROMPT_VARIANT", "A").upper() == "B":
        prompt += """ 优先直接承接最近对话的指代、短回复、否定和诉求切换；回复先给结论，再给下一步，只问一个必要问题。"""
    try:
        from app.graph.nodes import llm
        response = await invoke_llm(llm, [
            SystemMessage(content=prompt),
            HumanMessage(content=f"[事实]\n{json.dumps(facts, ensure_ascii=False)}\n\n[用户消息]\n{question}"),
        ], stage="grounded_fallback")
        text = str(getattr(response, "content", "") or "").strip()
        if text:
            return text
    except Exception:
        pass
    return "我已经收到你的情况。为了避免误处理，请告诉我是商品、物流还是售后问题；如果和订单有关，也可以直接选择对应订单。"
