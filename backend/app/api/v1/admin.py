"""面向售后专员的人工审核 API。"""
from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlmodel import select

from app.core.database import async_session_maker
from app.core.security import get_admin_user_id
from app.models.attachment import Attachment
from app.models.audit import AuditAction, AuditLog
from app.models.conversation import ChatMessage
from app.models.message import MessageCard, MessageStatus, MessageType
from app.models.notification import Notification
from app.models.order import Order, OrderStatus
from app.models.refund import RefundApplication, RefundStatus
from app.models.user import User
from app.services.conversation_service import add_message
from app.services.after_sales import after_sales_payload
from app.tasks.refund_tasks import process_refund_payment, send_refund_sms
from app.websocket.manager import manager

router = APIRouter()

AUDIT_ACTION_LABELS = {
    "PENDING": "等待审核", "APPROVE": "已同意", "REJECT": "已拒绝",
    "ESCALATE": "等待补充材料", "CANCELLED": "用户已撤销",
}
REFUND_STATUS_LABELS = {
    "USER_CONFIRM": "待用户确认", "SUBMITTED": "申请已提交", "WAITING_RETURN": "等待寄回商品",
    "RETURN_SHIPPING": "退货运输中", "MERCHANT_RECEIVED": "商家已收货", "PENDING": "等待审核",
    "NEED_INFO": "等待补充材料", "APPROVED": "审核通过", "PROCESSING": "退款处理中",
    "REJECTED": "审核未通过", "COMPLETED": "退款成功", "CANCELLED": "已取消",
}
ORDER_STATUS_LABELS = {
    "PENDING": "待付款", "PAID": "待发货", "SHIPPED": "运输中", "INTERCEPTING": "拦截中", "DELIVERED": "已签收",
    "REFUNDING": "退款处理中", "REFUNDED": "已退款", "CANCELLED": "已取消",
}


def _value(item: object) -> str:
    return str(getattr(item, "value", item) or "")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _client_thread_id(user_id: int, thread_id: str) -> str:
    prefix = f"{user_id}_"
    return thread_id[len(prefix):] if thread_id.startswith(prefix) else thread_id


def _timeline(refund: RefundApplication) -> List[Dict[str, Any]]:
    try:
        value = json.loads(refund.timeline or "[]")
        return value if isinstance(value, list) else []
    except Exception:
        return []


def _append_timeline(refund: RefundApplication, label: str, note: str) -> None:
    items = _timeline(refund)
    items.append({"label": label, "note": note, "time": _now().isoformat()})
    refund.timeline = json.dumps(items, ensure_ascii=False)


def _after_sales_type(refund: Optional[RefundApplication], snapshot: Dict[str, Any]) -> str:
    text = " ".join([
        str(snapshot.get("after_sales_type") or ""), str(snapshot.get("user_request") or ""),
        str(getattr(refund, "reason_detail", "") or ""),
    ])
    if "换货" in text:
        return "换货"
    if "仅退款" in text or "只退款" in text:
        return "仅退款"
    if any(word in text for word in ("破损", "少件", "错发", "漏发", "质量")):
        return "商品异常售后"
    return "退货退款"


class AuditTask(BaseModel):
    audit_log_id: int
    thread_id: str
    user_id: int
    refund_application_id: Optional[int]
    after_sales_id: Optional[int] = None
    after_sales_status: Optional[str] = None
    after_sales_status_label: Optional[str] = None
    order_id: Optional[int]
    trigger_reason: str
    risk_level: str
    action: str
    action_label: str
    admin_comment: Optional[str] = None
    context_snapshot: Dict[str, Any]
    created_at: str
    reviewed_at: Optional[str] = None
    user: Optional[Dict[str, Any]] = None
    order: Optional[Dict[str, Any]] = None
    refund: Optional[Dict[str, Any]] = None
    attachments: List[Dict[str, Any]] = Field(default_factory=list)
    conversation: List[Dict[str, Any]] = Field(default_factory=list)
    agent_checks: List[str] = Field(default_factory=list)
    policy_checks: List[str] = Field(default_factory=list)
    audit_history: List[Dict[str, Any]] = Field(default_factory=list)
    operation_log: List[Dict[str, Any]] = Field(default_factory=list)


class AdminDecisionRequest(BaseModel):
    action: str
    admin_comment: Optional[str] = None


class AdminDecisionResponse(BaseModel):
    success: bool
    message: str
    audit_log_id: int
    action: str


def _order_view(order: Order) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    for raw in order.items or []:
        if not isinstance(raw, dict):
            continue
        items.append({
            "name": str(raw.get("name") or "订单商品"), "qty": int(raw.get("qty") or 1),
            "price": float(raw.get("price") or 0), "image_url": raw.get("image_url") or raw.get("image"),
            "attributes": {str(key): str(value) for key, value in raw.items()
                           if key not in {"name", "qty", "price", "image", "image_url"} and value is not None},
        })
    state = _value(order.status)
    return {
        "order_id": order.id or 0, "order_sn": order.order_sn, "status": state,
        "status_label": ORDER_STATUS_LABELS.get(state, state or "未知状态"),
        "total_amount": float(order.total_amount), "tracking_number": order.tracking_number,
        "shipping_address": order.shipping_address, "created_at": order.created_at.isoformat(), "items": items,
    }


async def _history(session, audit: AuditLog) -> List[Dict[str, Any]]:
    stmt = select(AuditLog).where(AuditLog.user_id == audit.user_id)
    if audit.refund_application_id:
        stmt = stmt.where(AuditLog.refund_application_id == audit.refund_application_id)
    elif audit.order_id:
        stmt = stmt.where(AuditLog.order_id == audit.order_id)
    else:
        stmt = stmt.where(AuditLog.thread_id == audit.thread_id)
    records = list((await session.exec(stmt.order_by(AuditLog.created_at.asc()))).all())
    admin_ids = {record.admin_id for record in records if record.admin_id}
    admins: Dict[int, User] = {}
    if admin_ids:
        result = await session.exec(select(User).where(User.id.in_(admin_ids)))
        admins = {item.id: item for item in result.all() if item.id}
    return [{
        "audit_log_id": record.id or 0, "action": _value(record.action),
        "action_label": AUDIT_ACTION_LABELS.get(_value(record.action), _value(record.action)),
        "reason": record.trigger_reason, "comment": record.admin_comment,
        "operator_name": (admins[record.admin_id].full_name or admins[record.admin_id].username)
                         if record.admin_id in admins else None,
        "created_at": record.created_at.isoformat(),
        "reviewed_at": record.reviewed_at.isoformat() if record.reviewed_at else None,
    } for record in records]


async def _task_response(session, audit: AuditLog) -> AuditTask:
    snapshot = dict(audit.context_snapshot or {})
    user = await session.get(User, audit.user_id)
    order = await session.get(Order, audit.order_id) if audit.order_id else None
    refund = await session.get(RefundApplication, audit.refund_application_id) if audit.refund_application_id else None
    after_sales = after_sales_payload(refund) if refund else {}
    thread_id = _client_thread_id(audit.user_id, audit.thread_id)

    messages = list((await session.exec(
        select(ChatMessage).where(ChatMessage.user_id == audit.user_id, ChatMessage.thread_id == thread_id)
        .order_by(ChatMessage.created_at.asc())
    )).all())
    conversation = [{
        "id": item.id or 0, "role": item.role, "content": item.content,
        "message_type": item.message_type, "created_at": item.created_at.isoformat(),
    } for item in messages]

    attachment_stmt = select(Attachment).where(Attachment.user_id == audit.user_id)
    attachment_stmt = attachment_stmt.where(
        Attachment.refund_application_id == refund.id if refund and refund.id else Attachment.thread_id == thread_id
    )
    attachments = list((await session.exec(attachment_stmt.order_by(Attachment.created_at.asc()))).all())
    attachment_views = [{
        "id": item.id or 0, "attachment_type": item.attachment_type, "filename": item.filename,
        "content_type": item.content_type, "url": item.url, "created_at": item.created_at.isoformat(),
        "is_new_material": item.created_at >= audit.created_at,
    } for item in attachments]

    history = await _history(session, audit)
    checks = [str(item) for item in snapshot.get("agent_checks", []) if str(item).strip()]
    if order and not any("订单状态" in item for item in checks):
        checks.insert(0, f"订单核验：订单 {order.order_sn} 当前为“{ORDER_STATUS_LABELS.get(_value(order.status), _value(order.status))}”")
    if refund and not any("退款金额" in item for item in checks):
        checks.append(f"退款金额核验：¥{float(refund.refund_amount):.2f}")
    policy_checks = [str(item) for item in snapshot.get("policy_checks", []) if str(item).strip()]
    if not policy_checks:
        policy_checks = ["已按订单状态、售后时限和风险规则完成自动核验", f"转人工原因：{audit.trigger_reason}"]

    operation_log: List[Dict[str, Any]] = []
    if refund:
        operation_log.extend({
            "time": str(event.get("time") or refund.updated_at.isoformat()),
            "title": str(event.get("label") or "售后状态更新"),
            "detail": str(event.get("note") or ""), "kind": "refund",
        } for event in _timeline(refund))
    operation_log.extend({
        "time": item.created_at.isoformat(), "title": "用户上传材料", "detail": item.filename, "kind": "attachment",
    } for item in attachments)
    operation_log.extend({
        "time": record["reviewed_at"] or record["created_at"],
        "title": f"审核任务 #{record['audit_log_id']}：{record['action_label']}",
        "detail": record["comment"] or record["reason"], "kind": "audit",
    } for record in history)
    operation_log.sort(key=lambda item: item["time"], reverse=True)

    action = _value(audit.action)
    return AuditTask(
        audit_log_id=audit.id or 0, thread_id=thread_id, user_id=audit.user_id,
        refund_application_id=audit.refund_application_id, after_sales_id=after_sales.get("after_sales_id"), after_sales_status=after_sales.get("after_sales_status"), after_sales_status_label=after_sales.get("after_sales_status_label"), order_id=audit.order_id,
        trigger_reason=audit.trigger_reason, risk_level=_value(audit.risk_level),
        action=action, action_label=AUDIT_ACTION_LABELS.get(action, action), admin_comment=audit.admin_comment,
        context_snapshot=snapshot, created_at=audit.created_at.isoformat(),
        reviewed_at=audit.reviewed_at.isoformat() if audit.reviewed_at else None,
        user={
            "user_id": user.id or audit.user_id, "nickname": user.full_name or user.username, "account": user.username,
            "phone": user.phone, "email": user.email, "registered_at": user.created_at.isoformat(),
        } if user else None,
        order=_order_view(order) if order else None,
        refund={
            "refund_id": refund.id or 0, **after_sales, "after_sales_type": _after_sales_type(refund, snapshot),
            "status": _value(refund.status), "status_label": REFUND_STATUS_LABELS.get(_value(refund.status), _value(refund.status)),
            "refund_amount": float(refund.refund_amount), "reason_detail": refund.reason_detail, "admin_note": refund.admin_note,
            "stage": refund.stage, "timeline": _timeline(refund),
        } if refund else None,
        attachments=attachment_views, conversation=conversation, agent_checks=checks, policy_checks=policy_checks,
        audit_history=history, operation_log=operation_log,
    )


@router.get("/admin/tasks", response_model=List[AuditTask])
async def get_audit_tasks(
    risk_level: Optional[str] = None, include_history: bool = Query(False),
    current_admin_id: int = Depends(get_admin_user_id),
):
    """默认返回待审队列；include_history 时返回历史任务。"""
    async with async_session_maker() as session:
        stmt = select(AuditLog)
        if include_history:
            stmt = stmt.where(AuditLog.action != AuditAction.PENDING).order_by(AuditLog.updated_at.desc()).limit(50)
        else:
            stmt = stmt.where(AuditLog.action == AuditAction.PENDING).order_by(AuditLog.created_at.desc())
        if risk_level:
            stmt = stmt.where(AuditLog.risk_level == risk_level)
        records = list((await session.exec(stmt)).all())
        return [await _task_response(session, item) for item in records]


@router.get("/admin/tasks/{audit_log_id}", response_model=AuditTask)
async def get_audit_task(audit_log_id: int, current_admin_id: int = Depends(get_admin_user_id)):
    async with async_session_maker() as session:
        audit = await session.get(AuditLog, audit_log_id)
        if not audit:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="审核任务不存在")
        return await _task_response(session, audit)


@router.post("/admin/resume/{audit_log_id}", response_model=AdminDecisionResponse)
async def admin_decision(
    audit_log_id: int, request: AdminDecisionRequest, current_admin_id: int = Depends(get_admin_user_id),
):
    """记录审核结论，并同步写回售后记录、通知和原始对话。"""
    action = request.action.upper().strip()
    if action not in {"APPROVE", "REJECT", "REQUEST_INFO"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不支持的审核操作")
    comment = (request.admin_comment or "").strip()
    if not comment:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="请填写审核说明，便于用户了解处理结果")

    async with async_session_maker() as session:
        audit = await session.get(AuditLog, audit_log_id)
        if not audit:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="审核任务不存在")
        if _value(audit.action) != AuditAction.PENDING.value:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该审核任务已经处理，不能重复操作")

        now = _now()
        audit.action = {"APPROVE": AuditAction.APPROVE, "REJECT": AuditAction.REJECT, "REQUEST_INFO": AuditAction.ESCALATE}[action]
        audit.admin_id = current_admin_id
        audit.admin_comment = comment
        audit.reviewed_at = now
        audit.updated_at = now
        metadata = dict(audit.decision_metadata or {})
        metadata.update({"decision": action, "decision_at": now.isoformat(), "admin_comment": comment})
        audit.decision_metadata = metadata
        session.add(audit)

        refund = await session.get(RefundApplication, audit.refund_application_id) if audit.refund_application_id else None
        order = await session.get(Order, audit.order_id) if audit.order_id else None
        if refund:
            refund.reviewed_by = current_admin_id
            refund.reviewed_at = now
            refund.updated_at = now

        if action == "APPROVE":
            result_message = f"审核已通过：{comment}"
            if refund:
                refund.status, refund.stage, refund.admin_note = RefundStatus.PROCESSING, "退款处理中", comment
                _append_timeline(refund, "审核通过", comment)
            if order:
                order.status, order.updated_at = OrderStatus.REFUNDING, now
                session.add(order)
            if refund:
                try:
                    process_refund_payment.delay(refund_id=refund.id, amount=float(refund.refund_amount), payment_method="原支付方式")
                    send_refund_sms.delay(refund_id=refund.id, phone="138****1234", message=f"您的退款申请已通过，退款金额 ¥{refund.refund_amount} 将原路退回。")
                except Exception:
                    pass
        elif action == "REQUEST_INFO":
            result_message = f"审核人员需要你补充材料：{comment}"
            if refund:
                refund.status, refund.stage, refund.admin_note = RefundStatus.NEED_INFO, "等待补充材料", comment
                _append_timeline(refund, "等待补充材料", comment)
        else:
            result_message = f"审核未通过：{comment}"
            if refund:
                refund.status, refund.stage, refund.admin_note = RefundStatus.REJECTED, "审核未通过", comment
                _append_timeline(refund, "审核未通过", comment)
        if refund:
            session.add(refund)

        thread_id = _client_thread_id(audit.user_id, audit.thread_id)
        await add_message(
            session, audit.user_id, thread_id, "assistant", result_message,
            message_type="review_request" if action == "REQUEST_INFO" else "review_result",
            order_sn=order.order_sn if order else None,
            card_data={"audit_log_id": audit.id, "refund_application_id": audit.refund_application_id, "action": action, "admin_comment": comment},
        )
        session.add(MessageCard(
            thread_id=audit.thread_id, message_type=MessageType.AUDIT_CARD, status=MessageStatus.SENT,
            content={"card_type": "audit_result", "action": action, "message": result_message, "admin_comment": comment, "timestamp": now.isoformat()},
            sender_type="admin", sender_id=current_admin_id, receiver_id=audit.user_id,
        ))
        session.add(Notification(
            user_id=audit.user_id,
            title="需要补充售后材料" if action == "REQUEST_INFO" else "售后审核结果",
            content=result_message, target_type="after_sales", target_id=str(audit.refund_application_id or audit.id),
            meta_data={"audit_log_id": audit.id, "action": action, "thread_id": thread_id, **(after_sales_payload(refund) if refund else {})},
        ))
        await session.commit()

        if refund:
            await manager.notify_after_sales_change(thread_id, after_sales_payload(refund), result_message, user_id=audit.user_id)
        else:
            await manager.notify_status_change(thread_id=audit.thread_id, status=action, data={"message": result_message})
        return AdminDecisionResponse(success=True, message="审核结果已同步给用户", audit_log_id=audit_log_id, action=action)
