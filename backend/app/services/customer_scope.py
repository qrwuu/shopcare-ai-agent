"""Deterministic service boundary for the consumer-facing assistant.

The marketplace chat accepts open-ended text, but non-commerce knowledge must
not reach the model.  The gate is based on positive ecommerce service signals;
normal product, order and after-sales wording is always allowed through.
"""
from __future__ import annotations

import re


# Service signals cover actions and evidence a shopper would use.  They are
# intentionally broader than the recommendation trigger below: asking about a
# damaged product is a service request, not a product recommendation.
_SERVICE_TERMS = (
    "订单", "订单号", "下单", "购买", "买的", "物流", "快递", "发货", "签收", "收货", "到货",
    "地址", "退款", "退货", "退掉", "换货", "换个", "换成", "售后", "发票", "优惠券", "价保",
    "支付", "付款", "催发货", "取消", "修改地址", "库存", "规格", "尺码", "颜色", "运费",
    "价格", "便宜", "优惠", "金额", "实付", "图片", "照片", "凭证", "上传", "寄回", "面单",
    "破损", "少件", "少了", "少发", "漏发", "错发", "质量", "漏液", "退款到账", "售后进度", "审核", "投诉", "商家",
    "不想要", "不提交", "订单金额", "发错", "签收未收到", "查看商品", "商品详情", "商品属性",
    "有货", "现货", "缺货", "补货", "到货提醒", "物流拦截", "申请拦截", "拦截包裹", "拦截", "拦截进度", "拦截结果",
    "不喜欢", "不太喜欢", "不合适", "不需要了", "买错", "拍错", "未拆封", "拆封", "能不能退", "可不可以退", "无理由",
    "撤销", "撤销申请", "撤销售后", "撤销退款", "不想退", "不退了", "自己留着", "留着吧",
    "七天无理由", "7天无理由", "商品完好", "二次销售", "原路退回", "原支付路径", "运费险",
    "售后期限", "售后时效", "退款时效", "平台介入", "人工审核", "证据不足", "重复申请",
    "价格保护", "价保", "支付渠道", "账号隔离", "用户隐私", "隐私保护", "银行卡", "退到", "描述不一样", "与描述不符", "有杂音", "扎人", "配件", "催一下", "成功了吗", "拦下来", "拦下",
)
_PLATFORM_ACTION_PHRASES = (
    "人工客服", "转人工", "联系人工", "找客服", "客服介入", "投诉商家", "投诉店铺",
    "平台规则", "店铺活动", "活动规则", "领券", "优惠活动", "后台审核", "审核员",
)
_CATALOG_TERMS = (
    "内裤", "家居服", "睡衣", "短袖", "t恤", "衬衫", "衣服", "外套", "裤子", "阔腿裤",
    "裙子", "半身裙", "防晒衣", "防晒帽", "帽子", "鞋", "运动鞋", "双肩包", "背包", "书包",
    "斜挎包", "托特包", "保温杯", "水杯", "耳机", "充电宝", "充电器", "苹果充电器", "iphone", "风扇", "循环扇", "防晒霜",
    "护肤", "床品", "四件套", "毛巾", "洗衣液", "洗护", "洗发水", "沐浴露",
)
# Only explicit purchase/recommendation acts use the deterministic catalogue
# executor.  Do not put generic words such as “商品”“适合”“看看” here: they
# also occur in after-sales and product-detail questions.
_CORRECTION_MARKERS = ("我要的是", "我想要的是", "不是充电宝", "不是这个", "改成", "换成", "而是")

_PURCHASE_ACTIONS = (
    "推荐", "想买", "我要", "我想要", "买什么", "选什么", "哪款", "有没有", "挑", "给我找", "给我来",
    "送人", "礼物", "生日", "预算", "在售", "查看详情", "选择规格", "购买", "买一个", "买件",
)
_REFERENCE_TERMS = (
    "刚才那", "上次那", "推荐了什么", "第一个", "第二个", "第三个", "这款", "那款", "这件", "这套",
    "这个", "那个", "有黑色", "有白色", "小一码", "大一码", "确认", "继续", "算了",
)
_PRODUCT_FOLLOWUP_TERMS = (
    "查看商品", "商品详情", "商品属性", "材质", "面料", "成分", "怎么用", "如何用", "能用", "适合", "规格", "参数",
    "容量", "尺寸", "续航", "保温", "重量", "清洗", "保养", "保质期",
)
_GREETING_TERMS = ("你好", "您好", "在吗", "嗨", "hello", "hi")
_SUMMARY_TERMS = ("汇总", "总结", "刚才说什么", "上面说什么", "回顾")
_CATALOG_CONTEXT_FOLLOWUPS = (
    "什么时候", "啥时候", "何时", "多久", "几天", "几号", "还要等", "等多久",
    "到货没", "预算", "以内", "元以内", "快充", "护眼", "降噪", "优先", "卖完", "售罄", "替代", "别的颜色", "其他颜色", "提醒我", "能买", "还有吗",
)

_CONTEXT_ACKS = {"是", "是的", "对", "对的", "嗯", "嗯嗯", "好的", "好", "可以", "有", "没有", "不是", "提交", "提交吧", "确认提交", "申请", "继续申请", "确认申请", "办理", "继续办理"}


_OUT_OF_SCOPE_REPLY = (
    "这里是店铺客服，我只能处理店内商品、订单、物流、售后、支付和平台服务相关的问题。"
    "这类知识问答不在客服服务范围内，因此无法提供解释。\n\n"
    "如果你要咨询商品、订单或售后，直接告诉我具体情况就可以。"
)


def _normalise(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").lower())


def is_context_ack(question: str) -> bool:
    return _normalise(question) in _CONTEXT_ACKS


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _is_catalog_reference(text: str) -> bool:
    return (("刚才" in text or "上次" in text) and "推荐" in text) or _contains_any(text, _REFERENCE_TERMS)


def _is_catalog_spec_value(text: str) -> bool:
    if re.fullmatch(r"(?:我?(?:要|选))?(?:xs|s|m|l|xl|xxl|xxxl)(?:码)?", text, re.I):
        return True
    return bool(re.fullmatch(r"[\u4e00-\u9fff]{1,6}色", text))


def _looks_like_shipping_contact(text: str) -> bool:
    if re.search(r"(?<!\d)1[3-9]\d{9}(?!\d)", text):
        return True
    if _contains_any(text, ("收件人", "联系人", "联系电话", "手机号", "详细地址")):
        return True
    address_words = ("省", "市", "区", "县", "镇", "街道", "路", "号", "大学", "学院", "学校", "校区", "厦大", "小区", "公寓", "宿舍", "园区", "大厦", "广场", "社区", "楼", "室")
    if sum(1 for word in address_words if word in text) >= 1 and len(text) >= 4:
        return True
    regions = ("北京", "上海", "天津", "重庆", "福建", "广东", "浙江", "江苏", "山东", "河南", "河北", "湖南", "湖北", "四川", "江西", "安徽", "广西", "海南", "云南", "贵州", "陕西", "山西", "辽宁", "吉林", "黑龙江", "内蒙古", "宁夏", "新疆", "西藏", "青海", "甘肃", "香港", "澳门", "台湾")
    return len(text) >= 6 and any(region in text for region in regions)


def _looks_like_recipient_name(text: str) -> bool:
    value = text.strip()
    if re.fullmatch(r"[A-Za-z][A-Za-z .·-]{1,30}", value):
        return True
    common_surnames = set("赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜谢邹苏潘葛范彭鲁韦马苗方俞任袁柳鲍史唐费薛雷贺倪汤滕殷罗毕郝安常乐于傅齐康伍余顾孟平黄萧尹姚邵汪毛米戴宋庞熊纪舒项董梁杜阮蓝季贾路江童颜郭梅林钟徐邱骆高夏蔡田樊胡霍万卢莫房陆荣翁羊惠曲封储段巫焦巴侯全班仲伊宫宁仇甘祖武符刘景詹龙叶黎白蒲从索赖卓蒙池乔谭申冉牛边燕尚温庄晏柴阎连茹习艾向古易廖都耿满国文寇广东欧利越师聂辛简饶曾沙关查红游权盖益桓")
    return bool(re.fullmatch(r"[\u4e00-\u9fff·]{2,4}", value) and value[0] in common_surnames)


def is_product_recommendation_request(
    question: str,
    *,
    has_catalog_context: bool = False,
    previous_scope_question: str = "",
) -> bool:
    """Return true only for a purchase/recommendation request.

    A context follow-up is treated as a recommendation only when it contains a
    product noun from the simulated catalogue. This prevents “我先看看，不
    提交” or an after-sales complaint from being rewritten into product cards.
    """
    text = _normalise(question)
    if text.startswith(("查看详情:", "查看详情：", "选择规格:", "选择规格：")):
        return True
    if has_catalog_context and _is_catalog_spec_value(text):
        return True
    if not has_catalog_context and re.search(r"(?:刚才|之前).*(?:推荐|提到).*(?:什么|哪些|哪几|回顾|总结)|(?:推荐|提到)的都是什么", text):
        return False
    if _contains_any(text, _SERVICE_TERMS):
        return False
    if _contains_any(text, _PURCHASE_ACTIONS):
        return True
    if has_catalog_context and _contains_any(text, _CORRECTION_MARKERS):
        return True
    return has_catalog_context and _contains_any(text, _CATALOG_TERMS)


def customer_scope_reply(
    question: str,
    *,
    has_catalog_context: bool = False,
    has_pending_catalog_spec: bool = False,
    catalog_terms: tuple[str, ...] = (),
    pending_action: str = "",
    has_order_context: bool = False,
    previous_scope_question: str = "",
    previous_scope_kinds: tuple[str, ...] = (),
) -> str | None:
    """Return a local boundary reply, or ``None`` for an ecommerce task.

    The default remains deny for a pure non-commerce knowledge question. The
    allow-list deliberately accepts product attributes, evidence, refunds and
    conversational references so the boundary never degrades actual service.
    """
    text = _normalise(question)
    previous = _normalise(previous_scope_question)
    if not text or text in _GREETING_TERMS:
        return None

    if "银行卡" in text and _contains_any(text, ("退", "退款", "转到", "打到")):
        return "退款只能按订单的原支付路径、原金额退回，不能改到朋友或其他银行卡，也不能额外增加退款金额；这笔申请不会自动提交。若原支付账户无法使用，请先联系原支付渠道核实入账方式。"

    if has_pending_catalog_spec and is_context_ack(text):
        return None

    if pending_action and is_context_ack(text):
        return None

    if pending_action == "modify_address" and (
        _looks_like_shipping_contact(text) or _looks_like_recipient_name(text)
    ):
        return None
    if has_order_context and _looks_like_shipping_contact(text):
        return None

    if _contains_any(text, _SUMMARY_TERMS) and previous:
        return "刚才有一段不是店铺服务范围内的咨询，我没有展开回答；之后如果你想了解店内商品、订单、物流或售后，我可以继续按实际记录帮你处理。"

    if "拦截" in text and _contains_any(text, ("物流", "快递", "包裹", "订单", "发出", "运输")):
        return None
    if _contains_any(text, _SERVICE_TERMS) or _contains_any(text, _PLATFORM_ACTION_PHRASES):
        return None
    if _contains_any(text, _CATALOG_TERMS) or _is_catalog_reference(text):
        return None
    if has_catalog_context and (
        _is_catalog_spec_value(text)
        or _contains_any(text, _CATALOG_CONTEXT_FOLLOWUPS)
        or any(term and term in text for term in catalog_terms)
    ):
        return None
    if has_order_context and _contains_any(text, _PRODUCT_FOLLOWUP_TERMS):
        return None
    if is_product_recommendation_request(
        text,
        has_catalog_context=has_catalog_context,
        previous_scope_question=previous_scope_question,
    ):
        return None

    return _OUT_OF_SCOPE_REPLY
