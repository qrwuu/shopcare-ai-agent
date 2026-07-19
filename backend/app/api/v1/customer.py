# app/api/v1/customer.py
"""消费者端订单与售后记录 API。"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pathlib import Path
import json
import uuid
from fastapi import APIRouter, Depends, HTTPException, File, Form, UploadFile, status
from pydantic import BaseModel
from sqlmodel import select

from app.core.database import async_session_maker
from app.core.security import get_current_user_id
from app.models.order import Order
from app.models.refund import RefundApplication, RefundStatus
from app.models.attachment import Attachment
from app.models.audit import AuditLog, AuditAction, RiskLevel
from app.models.notification import Notification
from app.models.user import User
from app.services.demo_data import ensure_demo_orders_for_user
from app.services.conversation_service import add_message, get_or_create_session
from app.services.after_sales import after_sales_payload
from app.websocket.manager import manager

router = APIRouter()

ORDER_STATUS_LABELS = {
    "PENDING": "待付款",
    "PAID": "待发货",
    "SHIPPED": "运输中",
    "INTERCEPTING": "拦截中",
    "DELIVERED": "已签收",
    "REFUNDING": "退款处理中",
    "REFUNDED": "已退款",
    "CANCELLED": "已取消",
}

ACTIVE_ATTACHMENT_REFUND_STATUSES = {
    RefundStatus.USER_CONFIRM, RefundStatus.SUBMITTED, RefundStatus.WAITING_RETURN, RefundStatus.RETURN_SHIPPING,
    RefundStatus.PENDING, RefundStatus.NEED_INFO, RefundStatus.APPROVED, RefundStatus.PROCESSING,
    "USER_CONFIRM", "SUBMITTED", "WAITING_RETURN", "RETURN_SHIPPING", "PENDING", "NEED_INFO", "APPROVED", "PROCESSING",
}

REFUND_STATUS_LABELS = {
    "USER_CONFIRM": "待确认",
    "SUBMITTED": "申请已提交",
    "WAITING_RETURN": "等待用户寄回",
    "RETURN_SHIPPING": "退货运输中",
    "MERCHANT_RECEIVED": "商家确认收货",
    "PENDING": "等待审核",
    "NEED_INFO": "待补充材料",
    "APPROVED": "审核通过",
    "PROCESSING": "退款处理中",
    "REJECTED": "审核未通过",
    "COMPLETED": "退款成功",
    "CANCELLED": "已取消",
}


class OrderItemResponse(BaseModel):
    name: str
    qty: int = 1
    price: float = 0
    image_url: Optional[str] = None


class OrderResponse(BaseModel):
    id: int
    order_sn: str
    product_name: str
    product_image: Optional[str] = None
    total_amount: float
    status: str
    status_label: str
    tracking_number: Optional[str] = None
    shipping_address: str
    created_at: str
    items: List[OrderItemResponse]


class AttachmentResponse(BaseModel):
    id: int
    attachment_type: str
    filename: str
    content_type: str
    url: str
    order_sn: Optional[str]
    refund_application_id: Optional[int]
    created_at: str


class NotificationResponse(BaseModel):
    id: int
    after_sales_id: Optional[int] = None
    after_sales_status: Optional[str] = None
    after_sales_status_label: Optional[str] = None
    title: str
    content: str
    target_type: str
    target_id: Optional[str]
    is_read: bool
    meta_data: Dict[str, Any]
    created_at: str


class ReturnTrackingRequest(BaseModel):
    tracking_number: str


class RefundRecordResponse(BaseModel):
    id: int
    after_sales_id: int
    after_sales_status: str
    after_sales_status_label: str
    order_id: int
    order_sn: Optional[str]
    product_name: str
    status: str
    status_label: str
    refund_amount: float
    reason_detail: str
    admin_note: Optional[str]
    stage: Optional[str] = None
    return_tracking_number: Optional[str] = None
    timeline: List[Dict[str, Any]] = []
    created_at: str
    updated_at: str




def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _timeline(refund: RefundApplication) -> List[Dict[str, Any]]:
    if not refund.timeline:
        return []
    try:
        data = json.loads(refund.timeline)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _set_timeline(refund: RefundApplication, label: str, note: str = "") -> None:
    items = _timeline(refund)
    items.append({"label": label, "note": note, "time": _now().isoformat()})
    refund.timeline = json.dumps(items, ensure_ascii=False)


def _attachment_response(item: Attachment) -> AttachmentResponse:
    return AttachmentResponse(
        id=item.id or 0,
        attachment_type=item.attachment_type,
        filename=item.filename,
        content_type=item.content_type,
        url=item.url,
        order_sn=item.order_sn,
        refund_application_id=item.refund_application_id,
        created_at=_format_time(item.created_at),
    )


def _notification_response(item: Notification) -> NotificationResponse:
    return NotificationResponse(
        id=item.id or 0,
        after_sales_id=int(item.target_id) if item.target_type == "after_sales" and str(item.target_id or "").isdigit() else None,
        after_sales_status=str((item.meta_data or {}).get("after_sales_status") or "") or None,
        after_sales_status_label=str((item.meta_data or {}).get("after_sales_status_label") or "") or None,
        title=item.title,
        content=item.content,
        target_type=item.target_type,
        target_id=item.target_id,
        is_read=item.is_read,
        meta_data=item.meta_data or {},
        created_at=_format_time(item.created_at),
    )

def _status_value(value: Any) -> str:
    return getattr(value, "value", value) or ""


def _format_time(value: datetime) -> str:
    return value.isoformat()


def _item_response(item: Dict[str, Any]) -> OrderItemResponse:
    return OrderItemResponse(
        name=str(item.get("name") or "商品"),
        qty=int(item.get("qty") or 1),
        price=float(item.get("price") or 0),
        image_url=item.get("image_url") or item.get("image"),
    )


def _order_response(order: Order) -> OrderResponse:
    raw_items = order.items or []
    items = [_item_response(item) for item in raw_items if isinstance(item, dict)]
    product_name = "、".join(item.name for item in items[:2]) or "订单商品"
    if len(items) > 2:
        product_name += f" 等 {len(items)} 件"
    status_value = _status_value(order.status)

    return OrderResponse(
        id=order.id or 0,
        order_sn=order.order_sn,
        product_name=product_name,
        product_image=items[0].image_url if items else None,
        total_amount=float(order.total_amount),
        status=status_value,
        status_label=ORDER_STATUS_LABELS.get(status_value, status_value or "未知状态"),
        tracking_number=order.tracking_number,
        shipping_address=order.shipping_address,
        created_at=_format_time(order.created_at),
        items=items,
    )


@router.get("/customer/orders", response_model=List[OrderResponse])
async def list_my_orders(current_user_id: int = Depends(get_current_user_id)):
    async with async_session_maker() as session:
        result = await session.execute(
            select(Order)
            .where(Order.user_id == current_user_id)
            .order_by(Order.created_at.desc())
        )
        return [_order_response(order) for order in result.scalars().all()]


@router.get("/customer/orders/{order_sn}", response_model=OrderResponse)
async def get_my_order(order_sn: str, current_user_id: int = Depends(get_current_user_id)):
    async with async_session_maker() as session:
        result = await session.execute(
            select(Order).where(Order.order_sn == order_sn.upper(), Order.user_id == current_user_id)
        )
        order = result.scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到该订单")
        return _order_response(order)


@router.get("/customer/refunds", response_model=List[RefundRecordResponse])
async def list_my_refunds(current_user_id: int = Depends(get_current_user_id)):
    async with async_session_maker() as session:
        result = await session.execute(
            select(RefundApplication, Order)
            .join(Order, RefundApplication.order_id == Order.id)
            .where(RefundApplication.user_id == current_user_id)
            .order_by(RefundApplication.created_at.desc())
        )
        records: List[RefundRecordResponse] = []
        for refund, order in result.all():
            order_view = _order_response(order)
            status_value = _status_value(refund.status)
            records.append(
                RefundRecordResponse(
                    id=refund.id or 0,
                    **after_sales_payload(refund),
                    order_id=refund.order_id,
                    order_sn=order.order_sn,
                    product_name=order_view.product_name,
                    status=status_value,
                    status_label=REFUND_STATUS_LABELS.get(status_value, status_value or "未知状态"),
                    refund_amount=float(refund.refund_amount),
                    reason_detail=refund.reason_detail,
                    admin_note=refund.admin_note,
                    stage=refund.stage,
                    return_tracking_number=refund.return_tracking_number,
                    timeline=_timeline(refund),
                    created_at=_format_time(refund.created_at),
                    updated_at=_format_time(refund.updated_at),
                )
            )
        return records


@router.post("/customer/demo-data/restore", response_model=List[OrderResponse])
async def restore_demo_data(current_user_id: int = Depends(get_current_user_id)):
    async with async_session_maker() as session:
        user = await session.get(User, current_user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
        if user.is_admin:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="审核账号不能生成消费者体验订单")
        await ensure_demo_orders_for_user(session, user, reset=True)
        await session.commit()

    return await list_my_orders(current_user_id)


@router.post("/customer/attachments", response_model=AttachmentResponse)
async def upload_attachment(
    file: UploadFile = File(...),
    thread_id: str = Form(...),
    attachment_type: str = Form("image"),
    order_sn: Optional[str] = Form(None),
    refund_application_id: Optional[int] = Form(None),
    current_user_id: int = Depends(get_current_user_id),
):
    if attachment_type not in {"image", "evidence"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="附件类型不正确，请重新上传")
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="只能上传 JPG、PNG、WEBP 等图片文件")

    safe_suffix = Path(file.filename or "upload.jpg").suffix.lower() or ".jpg"
    if safe_suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="图片格式不支持，请上传 JPG、PNG、WEBP 或 GIF")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传文件为空，请重新选择图片")
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="图片不能超过 5MB，请压缩后再上传")

    normalized_order_sn = order_sn.upper() if order_sn else None

    async with async_session_maker() as session:
        linked_order: Optional[Order] = None
        linked_refund: Optional[RefundApplication] = None

        if normalized_order_sn:
            result = await session.exec(select(Order).where(Order.user_id == current_user_id, Order.order_sn == normalized_order_sn))
            linked_order = result.first()
            if not linked_order:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到该订单")

        if refund_application_id:
            linked_refund = await session.get(RefundApplication, refund_application_id)
            if not linked_refund or linked_refund.user_id != current_user_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到该售后申请")
            if linked_order and linked_refund.order_id != linked_order.id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="凭证和当前订单不匹配，请重新选择订单")
        elif attachment_type == "evidence" and linked_order:
            result = await session.exec(
                select(RefundApplication)
                .where(RefundApplication.user_id == current_user_id, RefundApplication.order_id == linked_order.id)
                .order_by(RefundApplication.updated_at.desc())
            )
            linked_refund = next((item for item in result.all() if item.status in ACTIVE_ATTACHMENT_REFUND_STATUSES), None)
            if linked_refund and linked_refund.id:
                refund_application_id = linked_refund.id

        upload_dir = Path(__file__).resolve().parents[3] / "uploads" / "evidence"
        upload_dir.mkdir(parents=True, exist_ok=True)
        stored_name = f"{current_user_id}_{uuid.uuid4().hex}{safe_suffix}"
        (upload_dir / stored_name).write_bytes(content)
        public_url = f"/uploads/evidence/{stored_name}"

        await get_or_create_session(session, current_user_id, thread_id, normalized_order_sn)
        attachment = Attachment(
            user_id=current_user_id,
            thread_id=thread_id,
            order_sn=normalized_order_sn,
            refund_application_id=refund_application_id,
            attachment_type=attachment_type,
            filename=file.filename or stored_name,
            content_type=file.content_type,
            url=public_url,
        )
        session.add(attachment)
        await session.flush()

        if attachment_type == "evidence" and linked_refund:
            if linked_refund.status in {RefundStatus.NEED_INFO, "NEED_INFO"}:
                linked_refund.status = RefundStatus.PENDING
                linked_refund.stage = "等待审核"
                linked_refund.admin_note = "已收到补充凭证，等待审核人员继续核实。"
                linked_refund.updated_at = _now()
                _set_timeline(linked_refund, "已补充凭证", "用户在原对话上传了售后凭证")
                pending_result = await session.exec(
                    select(AuditLog).where(
                        AuditLog.user_id == current_user_id,
                        AuditLog.refund_application_id == linked_refund.id,
                        AuditLog.action == AuditAction.PENDING,
                    )
                )
                if not pending_result.first():
                    session.add(AuditLog(
                        thread_id=thread_id,
                        order_id=linked_refund.order_id,
                        refund_application_id=linked_refund.id,
                        user_id=current_user_id,
                        trigger_reason="用户已补充售后凭证，需要继续人工核实",
                        risk_level=RiskLevel.MEDIUM,
                        action=AuditAction.PENDING,
                        context_snapshot={
                            "order_sn": normalized_order_sn,
                            "refund_application_id": linked_refund.id,
                            "attachment_id": attachment.id,
                            "resume_from_need_info": True,
                        },
                    ))
                session.add(linked_refund)
                session.add(Notification(
                    user_id=current_user_id,
                    title="凭证已补充",
                    content="售后凭证已收到，审核人员会继续核实。",
                    target_type="after_sales",
                    target_id=str(linked_refund.id),
                ))

        await add_message(
            session,
            current_user_id,
            thread_id,
            "system",
            message_type="attachment_card",
            order_sn=attachment.order_sn,
            card_data={
                "id": attachment.id,
                "attachment_type": attachment.attachment_type,
                "filename": attachment.filename,
                "content_type": attachment.content_type,
                "url": attachment.url,
                "order_sn": attachment.order_sn,
                "refund_application_id": attachment.refund_application_id,
            },
        )
        await session.commit()
        await session.refresh(attachment)
        return _attachment_response(attachment)


@router.get("/customer/notifications", response_model=List[NotificationResponse])
async def list_notifications(current_user_id: int = Depends(get_current_user_id)):
    async with async_session_maker() as session:
        result = await session.exec(select(Notification).where(Notification.user_id == current_user_id).order_by(Notification.created_at.desc()))
        return [_notification_response(item) for item in result.all()]


@router.post("/customer/notifications/read-after-sales", response_model=List[NotificationResponse])
async def mark_after_sales_notifications_read(current_user_id: int = Depends(get_current_user_id)):
    """Acknowledge after-sales notifications when the customer opens that inbox."""
    async with async_session_maker() as session:
        result = await session.exec(
            select(Notification)
            .where(Notification.user_id == current_user_id, Notification.target_type == "after_sales", Notification.is_read == False)
            .order_by(Notification.created_at.desc())
        )
        items = list(result.all())
        for item in items:
            item.is_read = True
            session.add(item)
        await session.commit()
        return [_notification_response(item) for item in items]


@router.post("/customer/notifications/{notification_id}/read", response_model=NotificationResponse)
async def mark_notification_read(notification_id: int, current_user_id: int = Depends(get_current_user_id)):
    async with async_session_maker() as session:
        item = await session.get(Notification, notification_id)
        if not item or item.user_id != current_user_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="通知不存在")
        item.is_read = True
        session.add(item)
        await session.commit()
        await session.refresh(item)
        return _notification_response(item)


async def _get_refund_for_user(session, refund_id: int, user_id: int) -> RefundApplication:
    refund = await session.get(RefundApplication, refund_id)
    if not refund or refund.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="售后申请不存在")
    return refund


@router.post("/customer/refunds/{refund_id}/return-tracking", response_model=RefundRecordResponse)
async def submit_return_tracking(refund_id: int, request: ReturnTrackingRequest, current_user_id: int = Depends(get_current_user_id)):
    async with async_session_maker() as session:
        refund = await _get_refund_for_user(session, refund_id, current_user_id)
        order = await session.get(Order, refund.order_id)
        if refund.status not in [RefundStatus.WAITING_RETURN, "WAITING_RETURN"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前售后还不能填写退货物流")
        refund.return_tracking_number = request.tracking_number.strip().upper()
        refund.status = RefundStatus.RETURN_SHIPPING
        refund.stage = "退货运输中"
        refund.admin_note = "已收到退货物流单号，等待商家确认收货。"
        refund.updated_at = _now()
        _set_timeline(refund, "退货运输中", f"退货单号 {refund.return_tracking_number}")
        session.add(refund)
        await session.commit()
        await session.refresh(refund)
        await manager.notify_after_sales_change("", after_sales_payload(refund), user_id=current_user_id)
        order_view = _order_response(order) if order else None
        status_value = _status_value(refund.status)
        return RefundRecordResponse(
            id=refund.id or 0, **after_sales_payload(refund), order_id=refund.order_id, order_sn=order.order_sn if order else None,
            product_name=order_view.product_name if order_view else "订单商品", status=status_value,
            status_label=REFUND_STATUS_LABELS.get(status_value, status_value), refund_amount=float(refund.refund_amount),
            reason_detail=refund.reason_detail, admin_note=refund.admin_note, stage=refund.stage,
            return_tracking_number=refund.return_tracking_number, timeline=_timeline(refund),
            created_at=_format_time(refund.created_at), updated_at=_format_time(refund.updated_at),
        )


@router.post("/customer/refunds/{refund_id}/simulate-received", response_model=RefundRecordResponse)
async def simulate_merchant_received(refund_id: int, current_user_id: int = Depends(get_current_user_id)):
    async with async_session_maker() as session:
        refund = await _get_refund_for_user(session, refund_id, current_user_id)
        order = await session.get(Order, refund.order_id)
        if refund.status not in [RefundStatus.RETURN_SHIPPING, "RETURN_SHIPPING"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="需要先填写退货物流单号")
        refund.status = RefundStatus.PROCESSING
        refund.stage = "退款处理中"
        refund.admin_note = "商家已确认收货，退款进入原路退回流程。"
        refund.updated_at = _now()
        _set_timeline(refund, "商家确认收货", "已进入退款处理")
        _set_timeline(refund, "退款处理中", "预计 1-3 个工作日原路退回")
        if order:
            order.status = "REFUNDING"
            order.updated_at = _now()
            session.add(order)
        session.add(refund)
        session.add(Notification(user_id=current_user_id, title="退款处理中", content="商家已确认收货，退款正在原路退回。", target_type="after_sales", target_id=str(refund.id)))
        await session.commit()
        await session.refresh(refund)
        await manager.notify_after_sales_change("", after_sales_payload(refund), user_id=current_user_id)
        order_view = _order_response(order) if order else None
        status_value = _status_value(refund.status)
        return RefundRecordResponse(
            id=refund.id or 0, **after_sales_payload(refund), order_id=refund.order_id, order_sn=order.order_sn if order else None, product_name=order_view.product_name if order_view else "订单商品",
            status=status_value, status_label=REFUND_STATUS_LABELS.get(status_value, status_value), refund_amount=float(refund.refund_amount), reason_detail=refund.reason_detail,
            admin_note=refund.admin_note, stage=refund.stage, return_tracking_number=refund.return_tracking_number, timeline=_timeline(refund),
            created_at=_format_time(refund.created_at), updated_at=_format_time(refund.updated_at),
        )


@router.post("/customer/refunds/{refund_id}/simulate-complete", response_model=RefundRecordResponse)
async def simulate_refund_complete(refund_id: int, current_user_id: int = Depends(get_current_user_id)):
    async with async_session_maker() as session:
        refund = await _get_refund_for_user(session, refund_id, current_user_id)
        order = await session.get(Order, refund.order_id)
        if refund.status not in [RefundStatus.PROCESSING, "PROCESSING"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="退款还没有进入处理阶段")
        refund.status = RefundStatus.COMPLETED
        refund.stage = "退款成功"
        refund.admin_note = "退款已模拟原路退回。"
        refund.updated_at = _now()
        _set_timeline(refund, "退款成功", "款项已原路退回")
        if order:
            order.status = "REFUNDED"
            order.updated_at = _now()
            session.add(order)
        session.add(refund)
        session.add(Notification(user_id=current_user_id, title="退款成功", content="退款已原路退回，订单状态已更新为已退款。", target_type="after_sales", target_id=str(refund.id)))
        await session.commit()
        await session.refresh(refund)
        await manager.notify_after_sales_change("", after_sales_payload(refund), user_id=current_user_id)
        order_view = _order_response(order) if order else None
        status_value = _status_value(refund.status)
        return RefundRecordResponse(
            id=refund.id or 0, **after_sales_payload(refund), order_id=refund.order_id, order_sn=order.order_sn if order else None, product_name=order_view.product_name if order_view else "订单商品",
            status=status_value, status_label=REFUND_STATUS_LABELS.get(status_value, status_value), refund_amount=float(refund.refund_amount), reason_detail=refund.reason_detail,
            admin_note=refund.admin_note, stage=refund.stage, return_tracking_number=refund.return_tracking_number, timeline=_timeline(refund),
            created_at=_format_time(refund.created_at), updated_at=_format_time(refund.updated_at),
        )
