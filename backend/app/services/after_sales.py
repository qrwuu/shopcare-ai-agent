"""售后申请的唯一状态定义与跨端事件载荷。"""
from typing import Any, Dict

from app.models.refund import RefundApplication

AFTER_SALES_STATUS = {
    "USER_CONFIRM": ("pending_user_confirm", "等待用户确认"),
    "SUBMITTED": ("submitted", "申请已提交"),
    "NEED_INFO": ("waiting_evidence", "等待补充材料"),
    "PENDING": ("pending_review", "等待审核"),
    "APPROVED": ("approved", "审核通过"),
    "REJECTED": ("rejected", "审核未通过"),
    "WAITING_RETURN": ("waiting_return", "等待用户寄回"),
    "RETURN_SHIPPING": ("return_in_transit", "退货运输中"),
    "MERCHANT_RECEIVED": ("merchant_received", "商家已收货"),
    "PROCESSING": ("refund_processing", "退款处理中"),
    "COMPLETED": ("completed", "退款成功"),
    "CANCELLED": ("cancelled", "已取消"),
}


def raw_refund_status(value: object) -> str:
    return str(getattr(value, "value", value) or "")


def after_sales_state(value: object) -> tuple[str, str]:
    return AFTER_SALES_STATUS.get(raw_refund_status(value), ("draft", "草稿"))


def after_sales_payload(refund: RefundApplication) -> Dict[str, Any]:
    state, label = after_sales_state(refund.status)
    return {
        "after_sales_id": refund.id or 0,
        "after_sales_status": state,
        "after_sales_status_label": label,
        "refund_status": raw_refund_status(refund.status),
    }
