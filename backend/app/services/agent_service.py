"""面向消费者的售后执行逻辑。"""
from datetime import datetime, timezone
import json
import re
from typing import Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.database import async_session_maker
from app.models.audit import AuditAction, AuditLog, RiskLevel
from app.models.order import Order, OrderStatus
from app.models.refund import RefundApplication, RefundReason, RefundStatus
from app.models.notification import Notification
from app.models.conversation import ChatMessage, ChatSession
from app.tasks.refund_tasks import notify_admin_audit
from app.websocket.manager import manager
from app.services.policy_knowledge import answer_policy_question, is_policy_question
from app.services.conversation_context import recent_conversation_context
from app.services.catalog_recommendation import _available_options, _inventory_status, catalog_context_terms, catalog_follow_up_answer, is_similar_recommendation, similar_catalog_products
from app.services.agent_telemetry import invoke_llm, record_tool_event
from app.services.customer_scope import customer_scope_reply, is_context_ack
from app.services.demo_catalog import build_demo_products
from app.services.after_sales import after_sales_payload

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

REFUND_STATUS_LABELS = {
    "USER_CONFIRM": "待确认",
    "SUBMITTED": "申请已提交",
    "WAITING_RETURN": "等待用户寄回",
    "RETURN_SHIPPING": "退货运输中",
    "MERCHANT_RECEIVED": "商家确认收货",
    "PENDING": "人工审核中",
    "NEED_INFO": "待补充材料",
    "APPROVED": "审核通过",
    "PROCESSING": "退款处理中",
    "REJECTED": "审核未通过",
    "COMPLETED": "退款成功",
    "CANCELLED": "已取消",
}

ACTIVE_REFUND_STATUSES = {
    RefundStatus.USER_CONFIRM, RefundStatus.SUBMITTED, RefundStatus.WAITING_RETURN, RefundStatus.RETURN_SHIPPING,
    RefundStatus.MERCHANT_RECEIVED, RefundStatus.PENDING, RefundStatus.NEED_INFO, RefundStatus.APPROVED, RefundStatus.PROCESSING,
    "USER_CONFIRM", "SUBMITTED", "WAITING_RETURN", "RETURN_SHIPPING", "MERCHANT_RECEIVED", "PENDING", "NEED_INFO", "APPROVED", "PROCESSING",
}

AFTER_SALES_INTENTS = {"return_refund", "refund_only", "exchange", "damaged_or_missing"}
AFTER_SALES_INTENT_LABELS = {
    "return_refund": "退货退款",
    "refund_only": "仅退款",
    "exchange": "换货",
    "damaged_or_missing": "商品异常售后",
}

INTENT_NEEDS_ORDER = {
    "order_query",
    "logistics",
    "cancel_order",
    "cancel_interception",
    "modify_address",
    "return_refund",
    "refund_only",
    "exchange",
    "urge_shipping",
    "logistics_issue",
    "damaged_or_missing",
    "after_sales_status",
    "after_sales_intake",
    "product_detail",
    "cancel_after_sales",
    "price_negotiation",
    "context_confirm",
}

PRODUCT_NAME_ALIASES = {
    "云柔家居服套装": ["家居服", "睡衣", "衣服", "套装"],
    "便携保温杯": ["保温杯", "杯子", "水杯"],
    "轻量通勤双肩包": ["双肩包", "背包", "书包", "包"],
    "智能降噪耳机 Pro": ["耳机", "降噪耳机", "蓝牙耳机"],
    "香氛洗护旅行套装": ["洗护", "旅行套装", "洗护套装", "香氛", "沐浴露", "洗发水"],
}

PRICE_NEGOTIATION_KEYWORDS = ["优惠一点", "便宜一点", "便宜点", "再优惠", "打折", "折扣", "能便宜", "少一点"]
PRODUCT_DETAIL_KEYWORDS = [
    "规格", "尺码", "码数", "什么码", "选什么码", "多大码", "材质", "面料", "成分", "属性", "参数", "尺寸", "重量", "容量", "大小", "多大",
    "能装", "长宽高", "库存", "颜色", "香味", "香型", "香精", "成分表", "保质期", "质保", "保修", "防水", "防泼水", "适合", "适用",
    "孕妇", "儿童", "婴儿", "老人", "敏感肌", "过敏", "荨麻疹", "湿疹", "皮炎", "哮喘", "皮肤", "禁忌", "注意事项", "能用", "可以用", "可用",
    "怎么用", "如何清洗", "怎么清洗", "清洗", "洗护", "水洗", "机洗", "保存", "存放", "开封", "盖紧", "漏液", "洒了", "异味", "少了", "破包",
    "破瓶", "使用", "保温", "降噪", "双肩包", "背包", "耳机", "杯子", "衣服", "商品", "几岁", "谁背", "适合谁", "适合什么人", "小学生",
    "初中生", "高中生", "成年人", "ml", "升", "装多少水", "能装多少水", "续航多久", "续航多长", "能用多久",
]

PRESALES_PRODUCTS = [
    {
        "id": "underwear-ice-silk-brief",
        "name": "冰丝无痕透气内裤",
        "category": "内裤",
        "image": "/product-images/underwear-ice-silk-brief.svg",
        "price": 39.0,
        "selling_points": ["冰丝凉感", "无痕贴合", "夏天透气不闷"],
        "colors": ["浅灰", "雾蓝", "肤色"],
        "sizes": ["M", "L", "XL", "XXL"],
        "stock_status": "现货充足",
        "keywords": ["内裤", "夏天", "透气", "凉感", "冰丝", "无痕", "轻薄", "不闷", "贴身"],
    },
    {
        "id": "underwear-cotton-antibacterial",
        "name": "新疆棉抗菌中腰内裤",
        "category": "内裤",
        "image": "/product-images/underwear-cotton-antibacterial.svg",
        "price": 49.0,
        "selling_points": ["纯棉亲肤", "中腰不勒", "日常耐穿"],
        "colors": ["白色", "浅灰", "黑色"],
        "sizes": ["M", "L", "XL", "XXL"],
        "stock_status": "M/L/XL 有货",
        "keywords": ["内裤", "纯棉", "棉", "抗菌", "亲肤", "中腰", "日常", "敏感", "舒适"],
    },
    {
        "id": "underwear-modal-boxer",
        "name": "莫代尔轻薄平角内裤",
        "category": "内裤",
        "image": "/product-images/underwear-modal-boxer.svg",
        "price": 45.0,
        "selling_points": ["莫代尔柔软", "平角防摩擦", "运动通勤都适合"],
        "colors": ["黑色", "藏青", "烟灰"],
        "sizes": ["L", "XL", "XXL", "XXXL"],
        "stock_status": "黑色/藏青库存较多",
        "keywords": ["内裤", "平角", "莫代尔", "柔软", "透气", "运动", "通勤", "大码", "防摩擦"],
    },
    {
        "id": "loungewear-soft-knit",
        "name": "云柔家居服套装",
        "category": "家居服",
        "image": "/product-images/loungewear-soft-knit.svg",
        "price": 129.0,
        "selling_points": ["棉感针织", "宽松亲肤", "适合空调房"],
        "colors": ["浅绿", "雾蓝"],
        "sizes": ["M", "L", "XL"],
        "stock_status": "M/L 有现货",
        "keywords": ["家居服", "睡衣", "夏天", "透气", "棉感", "宽松", "居家"],
    },
    {
        "id": "travel-wash-set",
        "name": "香氛洗护旅行套装",
        "category": "洗护",
        "image": "/product-images/travel-wash-set.svg",
        "price": 66.0,
        "selling_points": ["旅行装组合", "清爽花果香", "短途携带方便"],
        "colors": ["默认套装"],
        "sizes": ["旅行装"],
        "stock_status": "现货",
        "keywords": ["洗护", "旅行", "香氛", "洗发水", "沐浴露", "短途", "便携"],
    },
    {
        "id": "tshirt-coolmax-daily",
        "name": "凉感速干短袖 T 恤",
        "category": "T恤",
        "image": "/product-images/tshirt-coolmax-daily.svg",
        "price": 79.0,
        "selling_points": ["凉感速干", "不易粘身", "通勤运动两用"],
        "colors": ["白色", "浅灰", "雾蓝"],
        "sizes": ["S", "M", "L", "XL", "XXL"],
        "stock_status": "白色/浅灰库存充足",
        "keywords": ["T恤", "短袖", "夏天", "透气", "速干", "凉感", "运动", "通勤", "上衣"],
    },
    {
        "id": "fan-desk-quiet",
        "name": "静音循环桌面风扇",
        "category": "小家电",
        "image": "/product-images/fan-desk-quiet.svg",
        "price": 99.0,
        "selling_points": ["三档风量", "静音送风", "桌面宿舍两用"],
        "colors": ["奶油白", "雾蓝", "深灰"],
        "sizes": ["标准款"],
        "stock_status": "奶油白和雾蓝有现货",
        "keywords": ["风扇", "循环扇", "桌面风扇", "降温", "夏天", "宿舍", "静音", "小家电"],
    },
    {
        "id": "shirt-commute-oxford",
        "name": "免烫牛津纺通勤衬衫",
        "category": "衬衫",
        "image": "/product-images/shirt-commute-oxford.svg",
        "price": 119.0,
        "selling_points": ["微弹免烫", "版型利落", "上班面试都适合"],
        "colors": ["白色", "浅蓝", "条纹"],
        "sizes": ["S", "M", "L", "XL", "XXL"],
        "stock_status": "白色和浅蓝库存充足",
        "keywords": ["衬衫", "上衣", "通勤", "上班", "面试", "免烫", "正式", "男装", "女装"],
    },
    {
        "id": "pants-ice-wideleg",
        "name": "冰感垂顺阔腿裤",
        "category": "裤装",
        "image": "/product-images/pants-ice-wideleg.svg",
        "price": 109.0,
        "selling_points": ["冰感面料", "垂顺显瘦", "久坐不闷"],
        "colors": ["黑色", "奶茶色", "烟灰"],
        "sizes": ["S", "M", "L", "XL"],
        "stock_status": "黑色常用尺码有货",
        "keywords": ["裤子", "阔腿裤", "长裤", "夏天", "凉感", "通勤", "显瘦", "不闷", "女装"],
    },
    {
        "id": "skirt-a-line-summer",
        "name": "高腰 A 字半身裙",
        "category": "裙装",
        "image": "/product-images/skirt-a-line-summer.svg",
        "price": 99.0,
        "selling_points": ["高腰修饰比例", "A 字版型", "通勤约会都能穿"],
        "colors": ["黑色", "杏色", "雾蓝"],
        "sizes": ["S", "M", "L", "XL"],
        "stock_status": "杏色和黑色有现货",
        "keywords": ["裙子", "半身裙", "A字裙", "通勤", "约会", "夏天", "显瘦", "女装"],
    },
    {
        "id": "sunproof-jacket-light",
        "name": "轻薄防晒透气外套",
        "category": "防晒衣",
        "image": "/product-images/sunproof-jacket-light.svg",
        "price": 139.0,
        "selling_points": ["轻薄防晒", "可收纳帽檐", "户外通勤适合"],
        "colors": ["米白", "浅蓝", "薄荷绿"],
        "sizes": ["M", "L", "XL"],
        "stock_status": "米白和浅蓝有货",
        "inventory_by_color": {"米白": "in_stock", "浅蓝": "in_stock", "薄荷绿": "out_of_stock"},
        "restock_eta_by_color": {"薄荷绿": "预计 3–5 个工作日补货"},
        "keywords": ["防晒衣", "外套", "防晒", "夏天", "轻薄", "透气", "户外", "通勤"],
    },
    {
        "id": "sunproof-hat-upf50",
        "name": "UPF50+ 轻便防晒帽",
        "category": "防晒帽",
        "image": "/product-images/sunproof-hat-upf50.svg",
        "price": 59.0,
        "selling_points": ["UPF50+ 防晒", "帽檐可调", "通勤户外都方便"],
        "colors": ["米白", "卡其", "黑色"],
        "sizes": ["均码可调节"],
        "stock_status": "米白和卡其有现货",
        "keywords": ["防晒", "防晒帽", "帽子", "遮阳", "夏天", "轻便", "户外", "通勤"],
    },
    {
        "id": "sunproof-hat-wide-brim",
        "name": "大檐遮阳防晒渔夫帽",
        "category": "防晒帽",
        "image": "/product-images/sunproof-hat-wide-brim.svg",
        "price": 69.0,
        "selling_points": ["大帽檐遮脸", "可折叠收纳", "户外防晒更稳"],
        "colors": ["米白", "浅卡其", "黑色"],
        "sizes": ["均码可调节"],
        "stock_status": "米白有现货",
        "keywords": ["防晒帽", "帽子", "遮阳帽", "渔夫帽", "大檐", "防晒", "户外", "夏天"],
    },
    {
        "id": "sunproof-hat-visor-fold",
        "name": "可折叠空顶防晒帽",
        "category": "防晒帽",
        "image": "/product-images/sunproof-hat-visor-fold.svg",
        "price": 49.0,
        "selling_points": ["空顶不闷", "帽檐加宽", "骑行散步适合"],
        "colors": ["奶茶色", "浅灰", "黑色"],
        "sizes": ["均码可调节"],
        "stock_status": "浅灰和黑色有货",
        "keywords": ["防晒帽", "帽子", "遮阳帽", "空顶帽", "夏天", "不闷", "骑行", "散步"],
    },
    {
        "id": "sneaker-cloud-walk",
        "name": "云感缓震休闲运动鞋",
        "category": "运动鞋",
        "image": "/product-images/sneaker-cloud-walk.svg",
        "price": 239.0,
        "selling_points": ["缓震软弹", "网面透气", "久走不累"],
        "colors": ["白灰", "黑白", "燕麦色"],
        "sizes": ["36", "37", "38", "39", "40", "41", "42", "43", "44"],
        "stock_status": "常用尺码库存充足",
        "keywords": ["鞋", "运动鞋", "休闲鞋", "走路", "缓震", "透气", "跑步", "久站", "通勤"],
    },
    {
        "id": "backpack-commute-light",
        "name": "轻量通勤双肩包",
        "category": "双肩包",
        "image": "/product-images/backpack-commute-light.svg",
        "price": 159.0,
        "selling_points": ["18L 容量", "13 寸电脑位", "基础防泼水"],
        "colors": ["黑色", "灰蓝", "卡其"],
        "sizes": ["18L"],
        "stock_status": "黑色现货较多",
        "keywords": ["包", "双肩包", "背包", "书包", "电脑包", "通勤", "上学", "旅行", "防泼水"],
    },
    {
        "id": "bag-summer-crossbody",
        "name": "夏日轻便斜挎包",
        "category": "双肩包",
        "image": "/product-images/bag-summer-crossbody.svg",
        "price": 89.0,
        "selling_points": ["轻便不压肩", "小物分区", "夏天出门好搭"],
        "colors": ["奶油白", "黑色", "浅卡其"],
        "sizes": ["小号", "中号"],
        "stock_status": "奶油白和黑色有货",
        "keywords": ["包", "斜挎包", "单肩包", "小包", "夏天", "轻便", "通勤", "出门", "搭配"],
    },
    {
        "id": "bag-canvas-tote",
        "name": "大容量帆布托特包",
        "category": "双肩包",
        "image": "/product-images/bag-canvas-tote.svg",
        "price": 69.0,
        "selling_points": ["容量够大", "上课通勤能装", "棉帆布耐用"],
        "colors": ["本白", "黑色", "咖色"],
        "sizes": ["标准款"],
        "stock_status": "本白款库存充足",
        "keywords": ["包", "托特包", "帆布包", "通勤", "上学", "容量", "轻便", "租房", "宿舍"],
    },
    {
        "id": "cup-vacuum-500ml",
        "name": "便携保温杯",
        "category": "杯具",
        "image": "/product-images/cup-vacuum-500ml.svg",
        "price": 88.0,
        "selling_points": ["约 500ml", "保温保冷", "通勤携带方便"],
        "colors": ["米白", "银灰", "墨绿"],
        "sizes": ["500ml"],
        "stock_status": "米白款有现货",
        "keywords": ["杯子", "水杯", "保温杯", "保温", "500ml", "通勤", "上课", "便携"],
    },
    {
        "id": "earphone-anc-pro",
        "name": "智能降噪耳机 Pro",
        "category": "耳机",
        "image": "/product-images/earphone-anc-pro.svg",
        "price": 899.0,
        "selling_points": ["主动降噪", "约 24 小时续航", "通勤办公适合"],
        "colors": ["白色", "黑色"],
        "sizes": ["标准版"],
        "stock_status": "白色有现货",
        "keywords": ["耳机", "蓝牙耳机", "降噪", "通勤", "办公", "续航", "运动", "数码"],
    },
    {
        "id": "earphone-open-sport",
        "name": "开放式运动蓝牙耳机",
        "category": "耳机",
        "image": "/product-images/earphone-open-sport.svg",
        "price": 299.0,
        "selling_points": ["开放不堵耳", "运动佩戴稳", "户外通勤都能用"],
        "colors": ["黑色", "米白", "薄荷绿"],
        "sizes": ["标准版"],
        "stock_status": "黑色和米白有货",
        "keywords": ["耳机", "蓝牙耳机", "开放式", "运动", "跑步", "通勤", "不堵耳", "数码"],
    },
    {
        "id": "earphone-lite-commute",
        "name": "半入耳轻巧通勤耳机",
        "category": "耳机",
        "image": "/product-images/earphone-lite-commute.svg",
        "price": 159.0,
        "selling_points": ["佩戴轻巧", "通话清晰", "性价比高"],
        "colors": ["白色", "浅蓝", "黑色"],
        "sizes": ["标准版"],
        "stock_status": "白色库存充足",
        "keywords": ["耳机", "蓝牙耳机", "半入耳", "通勤", "办公", "通话", "轻巧", "送礼", "数码"],
    },
    {
        "id": "powerbank-slim-10000",
        "name": "轻薄快充充电宝 10000mAh",
        "category": "数码配件",
        "image": "/product-images/powerbank-slim-10000.svg",
        "price": 129.0,
        "selling_points": ["10000mAh", "双向快充", "出差旅行轻便"],
        "colors": ["白色", "黑色", "浅紫"],
        "sizes": ["10000mAh"],
        "stock_status": "白色和黑色有货",
        "keywords": ["充电宝", "移动电源", "充电器", "苹果充电器", "iphone充电器", "快充", "数码", "手机", "旅行", "出差", "通勤", "续航"],
    },
    {
        "id": "charger-apple-20w",
        "name": "苹果 20W USB-C 快充充电器",
        "category": "充电器",
        "image": "/product-images/charger-apple-20w.svg",
        "price": 89.0,
        "selling_points": ["20W USB-C 快充", "适配 iPhone", "小巧便携"],
        "colors": ["白色"],
        "sizes": ["20W 单口"],
        "stock_status": "现货充足",
        "keywords": ["充电器", "苹果", "iphone", "20w", "usb-c", "快充", "手机"],
    },
    {
        "id": "charger-apple-35w-dual",
        "name": "苹果 35W 双 USB-C 充电器",
        "category": "充电器",
        "image": "/product-images/charger-apple-20w.svg",
        "price": 149.0,
        "selling_points": ["35W 双口快充", "可同时充手机和耳机", "适配 iPhone"],
        "colors": ["白色"],
        "sizes": ["35W 双口"],
        "stock_status": "现货",
        "keywords": ["充电器", "苹果", "iphone", "35w", "双口", "usb-c", "快充", "手机"],
    },
    {
        "id": "sunscreen-daily-sensitive",
        "name": "清爽防晒乳 SPF50",
        "category": "护肤",
        "image": "/product-images/sunscreen-daily-sensitive.svg",
        "price": 89.0,
        "selling_points": ["清爽不黏", "日常通勤防晒", "成膜较快"],
        "colors": ["默认款"],
        "sizes": ["50ml"],
        "stock_status": "现货",
        "keywords": ["防晒", "防晒霜", "防晒乳", "护肤", "夏天", "清爽", "敏感肌", "通勤", "户外"],
    },
    {
        "id": "sunscreen-moisture-cream",
        "name": "水感保湿防晒霜 SPF50+",
        "category": "护肤",
        "image": "/product-images/sunscreen-moisture-cream.svg",
        "price": 99.0,
        "selling_points": ["保湿不拔干", "适合空调房", "日常通勤友好"],
        "colors": ["默认款"],
        "sizes": ["50g"],
        "stock_status": "现货",
        "keywords": ["防晒", "防晒霜", "护肤", "保湿", "不拔干", "通勤", "夏天", "干皮"],
    },
    {
        "id": "sunscreen-oilcontrol-gel",
        "name": "控油轻薄防晒凝露 SPF50",
        "category": "护肤",
        "image": "/product-images/sunscreen-oilcontrol-gel.svg",
        "price": 79.0,
        "selling_points": ["轻薄成膜", "油皮更清爽", "不易闷黏"],
        "colors": ["默认款"],
        "sizes": ["45ml"],
        "stock_status": "现货",
        "keywords": ["防晒", "防晒霜", "防晒乳", "防晒凝露", "护肤", "控油", "清爽", "油皮", "夏天", "不闷"],
    },
    {
        "id": "bedding-cotton-set",
        "name": "全棉四件套",
        "category": "床品",
        "image": "/product-images/bedding-cotton-set.svg",
        "price": 199.0,
        "selling_points": ["全棉亲肤", "四季可用", "宿舍租房友好"],
        "colors": ["浅灰", "奶油白", "豆沙粉"],
        "sizes": ["1.2m床", "1.5m床", "1.8m床"],
        "stock_status": "1.5m 和 1.8m 有货",
        "keywords": ["床品", "四件套", "床单", "被套", "全棉", "宿舍", "租房", "亲肤", "家居"],
    },
    {
        "id": "towel-soft-cotton",
        "name": "A 类纯棉吸水毛巾",
        "category": "家清日用",
        "image": "/product-images/towel-soft-cotton.svg",
        "price": 29.0,
        "selling_points": ["纯棉柔软", "吸水快", "日常洗脸洗澡适合"],
        "colors": ["白色", "浅灰", "浅粉"],
        "sizes": ["单条装", "三条装"],
        "stock_status": "三条装库存充足",
        "keywords": ["毛巾", "浴巾", "纯棉", "吸水", "日用", "家居", "宿舍", "洗澡", "洗脸"],
    },
    {
        "id": "laundry-detergent-lowfoam",
        "name": "低泡抑菌洗衣液",
        "category": "家清日用",
        "image": "/product-images/laundry-detergent-lowfoam.svg",
        "price": 39.0,
        "selling_points": ["低泡易漂", "淡香不冲", "内衣外衣都可分开洗"],
        "colors": ["薰衣草香", "清新皂香"],
        "sizes": ["1kg", "2kg"],
        "stock_status": "2kg 装有现货",
        "keywords": ["洗衣液", "洗衣", "家清", "清洁", "低泡", "抑菌", "淡香", "宿舍", "租房"],
    },
]

PRESALES_KEYWORDS = ["想买", "推荐", "有没有", "哪款", "哪一款", "适合", "买什么", "选什么", "怎么选", "挑一款", "商品推荐", "查看详情：", "查看详情:", "选择规格：", "选择规格:", "内裤", "家居服", "睡衣", "T恤", "短袖", "衬衫", "裤子", "阔腿裤", "裙子", "半身裙", "防晒", "遮阳", "防晒帽", "遮阳帽", "帽子", "防晒衣", "外套", "鞋", "运动鞋", "休闲鞋", "包", "双肩包", "背包", "书包", "电脑包", "斜挎包", "单肩包", "托特包", "帆布包", "杯子", "水杯", "保温杯", "耳机", "蓝牙耳机", "充电宝", "移动电源", "充电器", "苹果充电器", "iphone", "防晒霜", "护肤", "床品", "四件套", "毛巾", "浴巾", "洗衣液", "洗护", "洗发水", "沐浴露", "夏天穿", "透气", "凉快", "不闷", "通勤", "运动", "户外", "旅行", "出差", "上班", "上学", "宿舍", "租房", "送礼", "风扇", "循环扇", "桌面风扇", "降温"]
PRODUCT_CARD_MARKER = "PRODUCT_CARDS"



def classify_intent(question: str) -> str:
    if "银行卡" in question and _contains_any(question, ["退", "退款", "转到", "打到"]):
        return "refund_only"
    explicit_after_sales_words = ["仅退款", "只退款", "退货退款", "退货", "换货", "换一个"]
    if any(k in question for k in ["商品问题需要核验证据", "商品异常凭证", "照片凭证已补充"]) and not any(k in question for k in explicit_after_sales_words):
        return "damaged_or_missing"
    if is_policy_question(question):
        return "policy"
    if (("不是退款" in question or "不是要退款" in question) and any(k in question for k in ["价格", "金额", "贵", "价保"])):
        return "price_negotiation"
    if any(k in question for k in ["地址", "改地址", "修改地址"]) and any(k in question for k in ["取消", "不要了", "不想要"]):
        return "general"
    if any(k in question for k in ["不太喜欢", "不喜欢", "不合适"]) and any(k in question for k in ["想退", "退掉", "不要", "不保留"]):
        return "return_refund"
    if any(k in question for k in ["取消订单", "帮我取消", "取消这单", "这单取消", "取消吧"]) and "拦截" not in question:
        return "cancel_order"
    if any(k in question for k in ["人工", "投诉", "客服经理"]):
        return "human"
    if wants_cancel_after_sales(question):
        return "cancel_after_sales"
    if any(k in question for k in ["取消拦截", "撤销拦截", "停止拦截", "不用拦截", "不拦截了"]):
        return "cancel_interception"
    if any(k in question for k in ["售后进度", "退款进度", "申请进度", "处理到哪", "查看进度", "售后现在到哪", "售后到哪一步", "退款还没到账", "退款没到账"]):
        return "after_sales_status"
    if any(k in question for k in ["申请售后", "处理售后", "售后处理"]):
        return "after_sales_intake"
    if any(k in question for k in ["申请拦截", "拦截进度", "拦截结果", "拦截吧", "拦下来", "拦下包裹"]) or (
        "拦截" in question and any(k in question for k in ["物流", "快递", "包裹", "订单", "发出", "运输"])
    ):
        return "logistics_issue"
    if _contains_any(question, PRESALES_KEYWORDS) and not any(k in question for k in ["退货", "退款", "换货", "售后", "物流", "订单", "发票", "优惠券"]):
        return "presales"
    if any(k in question for k in ["查看商品", "商品详情", "商品属性", "查询商品属性", "这个商品", "这件商品", "该商品", "当前商品"]):
        return "product_detail"
    if any(k in question for k in ["发票", "抬头", "税号"]):
        return "invoice"
    if _contains_any(question, PRICE_NEGOTIATION_KEYWORDS):
        return "price_negotiation"
    if any(k in question for k in ["优惠券", "优惠码", "券", "优惠", "满减"]):
        return "coupon"
    if any(k in question for k in ["支付", "付款", "分期"]):
        return "payment"
    if any(k in question for k in ["物流异常", "没更新", "丢件", "卡住", "催物流", "申请拦截"]) or (
        "拦截" in question and any(k in question for k in ["物流", "快递", "包裹", "订单", "发出", "运输"])
    ):
        return "logistics_issue"
    if any(k in question for k in ["催发货", "怎么还没发", "快点发"]):
        return "urge_shipping"
    if any(k in question for k in ["换货", "换一个", "换货期限", "自动换货"]):
        return "exchange"
    if any(k in question for k in ["仅退款", "只退款", "仅退款处理期限", "自动仅退款"]):
        return "refund_only"
    if any(k in question for k in ["退货退款", "退货", "退款", "不要了", "七天无理由"]):
        return "return_refund"
    if any(k in question for k in ["补充凭证", "上传凭证", "少件", "少了", "少发", "漏发", "错发", "破损", "破洞", "质量有问题", "扎人", "有杂音", "杂音", "开线", "开裂", "裂了", "坏了", "漏液", "漏了", "洒了", "撒了", "破包", "破瓶", "描述不一样", "与描述不符", "货不对版", "瓶子漏", "洗发露漏", "洗发水漏"]):
        return "damaged_or_missing"
    if any(k in question for k in ["取消订单", "不想买", "取消"]):
        return "cancel_order"
    if any(k in question for k in ["修改地址", "改地址", "收货地址", "地址改", "确认修改"]):
        return "modify_address"
    if any(k in question for k in ["物流", "快递", "到哪", "签收"]):
        return "logistics"
    if any(k in question for k in ["订单", "订单状态", "买的"]):
        return "order_query"
    if _contains_any(question, PRODUCT_DETAIL_KEYWORDS):
        return "product"
    if any(k in question for k in ["继续申请", "确认申请", "确认提交", "帮我提交", "仍然申请", "要继续申请"]):
        return "context_confirm"
    return "general"


def needs_order(intent: str) -> bool:
    return intent in INTENT_NEEDS_ORDER


def extract_order_sn(question: str) -> Optional[str]:
    match = re.search(r"((?:SN|SC)\d+)", question, re.IGNORECASE)
    return match.group(1).upper() if match else None


def has_confirmed(question: str) -> bool:
    return any(k in question for k in ["确认", "确定", "同意", "继续办理", "按这个处理", "继续申请", "确认提交", "帮我提交", "仍然申请", "要继续申请"])


def has_declined(question: str) -> bool:
    return any(k in question for k in ["暂不申请", "先不申请", "不申请", "先不用", "不用了", "算了", "先不提交", "先看看", "我先看看", "不提交", "别取消了", "不要取消", "不取消了"])


def wants_cancel_after_sales(question: str) -> bool:
    cleaned = re.sub(r"\s+", "", question)
    return any(k in cleaned for k in [
        "撤销售后", "撤销申请", "取消售后", "撤销退款", "取消退款", "撤销退货", "取消退货",
        "取消仅退款", "撤销仅退款", "取消退货退款", "撤销退货退款",
        "取消退款申请", "取消退货申请", "不要退了", "不退了", "不想退了", "不需要退了",
        "不退款了", "不用退款了", "自己留着", "我留着", "留下吧", "留着吧",
        "算了撤销退款", "算了撤销", "撤销人工审核", "取消人工审核",
    ])


def is_subjective_return_reason(question: str) -> bool:
    cleaned = re.sub(r"\s+", "", question)
    return any(k in cleaned for k in [
        "不喜欢", "不合适", "买错了", "买错", "拍错了", "拍错",
        "不想要了", "不需要了", "改变主意", "尺码不合适", "颜色不喜欢",
    ])


def has_evidence(question: str) -> bool:
    return any(k in question for k in ["照片", "图片", "凭证", "面单", "开箱", "视频", "上传", "破损图", "证据"])


def has_product_problem(question: str) -> bool:
    return any(k in question for k in ["少件", "漏发", "错发", "破损", "破洞", "开线", "开裂", "裂了", "坏了", "质量问题", "不完整", "少发", "漏液", "漏了", "洒了", "撒了", "破包", "破瓶", "瓶子漏", "洗发露漏", "洗发水漏"])


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _is_soft_confirm(question: str) -> bool:
    cleaned = re.sub(r"\s+", "", question)
    if has_confirmed(question):
        return True
    return cleaned in {"好", "好的", "行", "可以", "继续", "继续吧", "就这个", "按这个", "那就这个", "麻烦了", "是", "是的", "对", "对的", "嗯", "嗯嗯", "申请", "办理", "提交", "提交吧"}


RETURN_WAREHOUSE_ADDRESS = "上海市闵行区申长路 88 号 ShopCare 售后仓，收件人：售后组，电话：400-820-8820"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _timeline_item(label: str, note: str = "") -> dict[str, str]:
    return {"label": label, "note": note, "time": _now().isoformat()}


def _append_timeline(refund: RefundApplication, label: str, note: str = "") -> None:
    try:
        items = json.loads(refund.timeline or "[]")
        if not isinstance(items, list):
            items = []
    except Exception:
        items = []
    items.append(_timeline_item(label, note))
    refund.timeline = json.dumps(items, ensure_ascii=False)




def _client_thread_id(user_id: int, thread_id: str) -> str:
    prefix = f"{user_id}_"
    return thread_id[len(prefix):] if thread_id.startswith(prefix) else thread_id


def _visible_question(question: str, order_sn: Optional[str]) -> str:
    text = question.strip()
    if order_sn:
        text = re.sub(rf"^订单号\s*{re.escape(order_sn.upper())}。?", "", text, flags=re.IGNORECASE).strip()
    return text




def _intent_from_confirmation_context(last_assistant: str) -> Optional[str]:
    if not last_assistant:
        return None
    if any(k in last_assistant for k in ["当前地址", "新地址", "确认无误后回复“确认修改”"]):
        return "modify_address"
    if any(k in last_assistant for k in ["取消订单并原路退款", "确认按这个方案处理", "优先取消订单"]):
        return "return_refund"
    if any(k in last_assistant for k in ["催发货提醒", "物流异常工单", "让商家和快递侧一起核实"]):
        return "logistics_issue"
    if any(k in last_assistant for k in ["人工核实", "还要继续申请", "人工再核实"]):
        if any(k in last_assistant for k in ["商品照片", "外包装", "面单", "商品异常", "凭证"]):
            return "damaged_or_missing"
        return "return_refund"
    if any(k in last_assistant for k in ["商品已经收到了吗", "退款原因", "退货退款、仅退款还是换货"]):
        return "return_refund"
    return None

def _looks_like_address(text: str) -> bool:
    cleaned = re.sub(r"\s+", "", text)
    if len(cleaned) > 120:
        return False
    if any(k in cleaned for k in ["订单", "物流", "退款", "退货", "换货", "发票", "优惠券", "商品"]):
        return False
    if "校区" in cleaned and len(cleaned) >= 5:
        return True
    if len(cleaned) < 8:
        return False
    address_words = ["省", "市", "区", "县", "镇", "街道", "路", "号", "大学", "校区", "小区", "楼", "室"]
    return sum(1 for word in address_words if word in cleaned) >= 2


def _looks_like_shipping_address_fragment(text: str) -> bool:
    """识别顾客自然输入的地址片段，包括校园和常见地区简称。"""
    cleaned = re.sub(r"\s+", "", text)
    if _looks_like_address(cleaned):
        return True
    if len(cleaned) >= 4 and any(word in cleaned for word in [
        "大学", "学院", "学校", "校区", "厦大", "小区", "公寓", "宿舍", "园区", "大厦", "广场", "社区",
    ]):
        return True
    regions = [
        "北京", "上海", "天津", "重庆", "福建", "广东", "浙江", "江苏", "山东", "河南", "河北",
        "湖南", "湖北", "四川", "江西", "安徽", "广西", "海南", "云南", "贵州", "陕西", "山西",
        "辽宁", "吉林", "黑龙江", "内蒙古", "宁夏", "新疆", "西藏", "青海", "甘肃", "香港", "澳门", "台湾",
    ]
    return len(cleaned) >= 6 and any(region in cleaned for region in regions)


_COMMON_CHINESE_SURNAMES = set(
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
    "戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳鲍史唐"
    "费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平"
    "黄和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋茅庞熊纪舒屈项祝"
    "董梁杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊"
    "胡凌霍虞万支柯昝管卢莫经房裘缪干解应宗丁宣贲邓郁单杭洪包诸左石"
    "崔吉龚程嵇邢滑裴陆荣翁荀羊惠甄曲家封芮羿储靳汲邴糜松井段富巫乌"
    "焦巴弓牧隗山谷车侯宓蓬全郗班仰秋仲伊宫宁仇栾暴甘钭厉戎祖武符刘"
    "景詹束龙叶幸司韶郜黎蓟薄印宿白怀蒲邰从鄂索咸籍赖卓蔺屠蒙池乔阴"
    "胥能苍双闻莘党翟谭贡劳逄姬申扶堵冉宰郦雍郤璩桑桂濮牛寿通边扈燕"
    "冀郏浦尚农温别庄晏柴瞿阎充慕连茹习宦艾鱼容向古易慎戈廖庾终暨居"
    "衡步都耿满弘匡国文寇广禄阙东欧利蔚越夔隆师巩厍聂晁勾敖融冷訾辛"
    "阚那简饶空曾毋沙乜养鞠须丰巢关蒯相查后荆红游竺权逯盖益桓公"
)


def _looks_like_unlabelled_recipient(text: str) -> bool:
    value = text.strip()
    if re.fullmatch(r"[A-Za-z][A-Za-z .·-]{1,30}", value):
        return True
    return bool(
        re.fullmatch(r"[\u4e00-\u9fff·]{2,4}", value)
        and value[0] in _COMMON_CHINESE_SURNAMES
    )


def _parse_shipping_contact(text: str) -> dict[str, str]:
    raw = re.sub(r"\s+", " ", text.strip())
    phone_match = re.search(r"(?<!\d)(1[3-9]\d{9})(?!\d)", raw)
    phone = phone_match.group(1) if phone_match else ""
    recipient_match = re.search(
        r"(?:收件人|联系人|姓名)\s*[:：]?\s*([A-Za-z\u4e00-\u9fff·]{2,20})(?=[，,；;\s]|\Z)", raw
    )
    recipient = recipient_match.group(1) if recipient_match else ""
    address_match = re.search(r"(?:详细地址|收货地址|新地址|地址)\s*[:：]?\s*(.+)\Z", raw)
    address = address_match.group(1).strip() if address_match else ""

    without_phone = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", " ", raw)
    without_phone = re.sub(r"^(?:改到|改为|改成|新地址|地址)\s*[:：]?", "", without_phone).strip(" ，,；;")
    tokens = without_phone.split()
    contact_commands = {
        "修改地址", "修改收货地址", "修改收货信息", "改地址", "我要修改地址", "我想修改地址",
        "我要改地址", "我想改地址", "收货地址", "新地址", "确认修改",
        "取消修改", "暂不申请", "先不修改", "不用了", "算了", "提交", "确认",
    }
    if not address and len(tokens) == 1 and _looks_like_shipping_address_fragment(tokens[0]):
        address = tokens[0]
    looks_like_address_command = len(tokens) == 1 and (
        any(verb in tokens[0] for verb in ["修改", "改成", "改为", "改到", "更换"])
        and any(noun in tokens[0] for noun in ["地址", "收货信息"])
    )
    if not recipient and not address and len(tokens) == 1 and tokens[0] not in contact_commands and not looks_like_address_command and _looks_like_unlabelled_recipient(tokens[0]):
        recipient = tokens[0]
    if not recipient and len(tokens) >= 2:
        if _looks_like_shipping_address_fragment(" ".join(tokens[:-1])) and _looks_like_unlabelled_recipient(tokens[-1]):
            recipient = tokens[-1]
            address = address or " ".join(tokens[:-1])
        elif _looks_like_shipping_address_fragment(" ".join(tokens[1:])) and _looks_like_unlabelled_recipient(tokens[0]):
            recipient = tokens[0]
            address = address or " ".join(tokens[1:])
    if not address:
        candidate = without_phone
        if recipient:
            candidate = re.sub(rf"(?:收件人|联系人|姓名)?\s*[:：]?\s*{re.escape(recipient)}", " ", candidate, count=1).strip(" ，,；;")
        if _looks_like_shipping_address_fragment(candidate):
            address = candidate
    return {"recipient": recipient, "phone": phone, "address": address}


def _missing_shipping_fields(state: dict) -> list[str]:
    labels = {"recipient": "收件人姓名", "phone": "联系电话", "address": "详细地址"}
    return [label for key, label in labels.items() if not str(state.get(key) or "").strip()]


def _format_shipping_contact(state: dict) -> str:
    if _missing_shipping_fields(state):
        return ""
    return f"收件人：{state['recipient']}；电话：{state['phone']}；地址：{state['address']}"


def _infer_order_follow_up_intent(
    question: str,
    last_assistant: str,
    order: Order,
    pending_address: Optional[str],
    pending_action: Optional[str],
    active_refund: Optional[RefundApplication],
) -> Optional[str]:
    cleaned = re.sub(r"\s+", "", question)
    status = str(getattr(order.status, "value", order.status))

    if pending_address or pending_action == "modify_address" or _contains_any(last_assistant, [
        "当前地址", "新地址", "确认无误后回复“确认修改”", "完整收货信息", "收件人姓名",
    ]):
        contact_fields = _parse_shipping_contact(question)
        if any(contact_fields.values()) or _looks_like_address(question) or _contains_any(cleaned, ["地址", "收货地址", "改到", "改为", "改成", "收件人", "联系电话", "手机号"]):
            return "modify_address"
        if pending_address and _is_soft_confirm(question):
            return "modify_address"

    if pending_action and _is_soft_confirm(question):
        return pending_action

    if active_refund:
        if extract_tracking_number(question) or _contains_any(cleaned, ["退货单号", "物流单号", "我寄了", "寄回了", "已经寄出", "已寄出", "发回去了"]):
            return "return_refund"
        if wants_cancel_after_sales(question) or _contains_any(cleaned, ["撤销申请", "取消申请", "不要退了", "不退了", "取消退款"]):
            return "cancel_after_sales"
        if _contains_any(cleaned, ["退货地址", "寄回地址", "寄到哪里", "怎么寄回", "怎么寄", "退到哪里", "现在要做什么", "下一步", "多久到账", "什么时候退款", "多久退款", "补什么", "缺什么", "需要什么材料", "售后进度", "退款进度", "处理到哪", "人工审核", "审核结果"]):
            return "return_refund"

    if _contains_any(cleaned, ["帮我催一下", "催一下", "继续催", "再催一下", "帮我催发货", "催发货", "申请拦截"]):
        if status in {"PENDING", "PAID", "SHIPPED", "INTERCEPTING"}:
            return "logistics_issue"
        return "logistics"

    if _contains_any(cleaned, ["物流呢", "包裹呢", "单号呢", "到哪了", "查一下物流", "看下物流", "继续查", "什么时候到", "签收了吗", "派送了吗", "查快递"]):
        return "logistics"

    if active_refund and _contains_any(cleaned, ["售后呢", "进度呢", "处理到哪", "现在怎么样", "下一步呢", "补材料", "补凭证", "上传凭证"]):
        return "return_refund"

    return None


def _active_refund_follow_up_reply(refund: RefundApplication, order: Order, question: str) -> Optional[str]:
    cleaned = re.sub(r"\s+", "", question)
    status = str(getattr(refund.status, "value", refund.status))
    note = refund.admin_note or "有新进展会继续同步给你。"

    if status == "WAITING_RETURN":
        if _contains_any(cleaned, ["退货地址", "寄回地址", "寄到哪里", "怎么寄回", "怎么寄", "退到哪里"]):
            return f"这笔售后已经提交好了，下一步是先把商品寄回。\n\n退货地址：{RETURN_WAREHOUSE_ADDRESS}\n寄出后把退货物流单号发给我，我会继续帮你更新进度。"
        if _contains_any(cleaned, ["现在要做什么", "下一步", "怎么处理", "多久到账", "什么时候退款", "多久退款"]):
            return "这笔售后当前还在等你寄回商品。\n\n你先把商品寄出，寄出后把退货物流单号发给我；商家确认收货后，才会继续进入退款处理。"

    if status == "RETURN_SHIPPING" and _contains_any(cleaned, ["到哪了", "进度", "处理到哪", "下一步", "什么时候退款", "多久退款"]):
        tracking = refund.return_tracking_number or "已登记"
        return f"我这边看到你已经寄出了，退货单号是 {tracking}，当前状态是“退货运输中”。\n\n接下来等商家确认收货后，就会进入退款处理。"

    if status == "MERCHANT_RECEIVED" and _contains_any(cleaned, ["到哪了", "进度", "下一步", "什么时候退款", "多久退款"]):
        return "商家已经确认收到退货了，下一步会进入退款处理。\n\n一般接下来会按原支付路径退回，你可以继续留意售后记录更新。"

    if status in {"APPROVED", "PROCESSING"} and _contains_any(cleaned, ["到哪了", "进度", "下一步", "什么时候退款", "多久退款", "到账"]):
        return f"这笔售后现在已经到“{_refund_status_label(refund.status)}”了。\n\n退款一般会按原支付路径退回，到账时间通常还要看支付渠道，常见是 1 到 5 个工作日。"

    if status == "PENDING" and _contains_any(cleaned, ["到哪了", "进度", "什么时候好", "多久", "审核结果"]):
        return f"这笔售后现在还在人工审核中。\n\n申请编号 #{refund.id}，{note} 一般会在 1 个工作日内继续更新。"

    if status == "NEED_INFO" and _contains_any(cleaned, ["缺什么", "补什么", "需要什么材料", "怎么补", "补材料", "补凭证"]):
        return f"这笔售后现在还在等你补材料。\n\n{note} 补充完成后直接发我，我会继续帮你推进。"

    if status == "COMPLETED" and _contains_any(cleaned, ["到账", "什么时候到", "多久到", "退款呢"]):
        return "这笔售后已经退款成功了。\n\n如果是刚完成，到账时间通常还要看原支付渠道，一般 1 到 5 个工作日内会显示。"

    return None


async def _chat_session(session: AsyncSession, user_id: int, thread_id: str) -> Optional[ChatSession]:
    client_thread_id = _client_thread_id(user_id, thread_id)
    result = await session.exec(select(ChatSession).where(ChatSession.user_id == user_id, ChatSession.thread_id == client_thread_id))
    return result.first()


async def _last_assistant_text(session: AsyncSession, user_id: int, thread_id: str) -> str:
    client_thread_id = _client_thread_id(user_id, thread_id)
    result = await session.exec(
        select(ChatMessage)
        .where(ChatMessage.user_id == user_id, ChatMessage.thread_id == client_thread_id, ChatMessage.role == "assistant")
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
    )
    msg = result.first()
    return msg.content if msg else ""


async def _get_pending_address_state(session: AsyncSession, user_id: int, thread_id: str, order_sn: str) -> dict:
    chat = await _chat_session(session, user_id, thread_id)
    pending = (chat.meta_data or {}).get("pending_address_change") if chat else None
    if isinstance(pending, dict) and str(pending.get("order_sn", "")).upper() == order_sn.upper():
        return dict(pending)
    return {}


async def _set_pending_address_draft(
    session: AsyncSession,
    user_id: int,
    thread_id: str,
    order_sn: str,
    fields: dict[str, str],
) -> dict:
    chat = await _chat_session(session, user_id, thread_id)
    if not chat:
        return {}
    meta = dict(chat.meta_data or {})
    previous = meta.get("pending_address_change")
    state = dict(previous) if isinstance(previous, dict) and str(previous.get("order_sn", "")).upper() == order_sn.upper() else {}
    state.update({"order_sn": order_sn, "created_at": state.get("created_at") or _now().isoformat()})
    for key in ("recipient", "phone", "address"):
        if str(fields.get(key) or "").strip():
            state[key] = str(fields[key]).strip()
    if state.get("recipient") and state.get("address"):
        address_tokens = str(state["address"]).split()
        if address_tokens and address_tokens[-1] == str(state["recipient"]):
            state["address"] = " ".join(address_tokens[:-1]).strip()
    state["new_address"] = _format_shipping_contact(state)
    meta["pending_address_change"] = state
    chat.meta_data = meta
    chat.updated_at = _now()
    session.add(chat)
    return state


async def _set_pending_address(session: AsyncSession, user_id: int, thread_id: str, order_sn: str, address: str) -> None:
    chat = await _chat_session(session, user_id, thread_id)
    if not chat:
        return
    meta = dict(chat.meta_data or {})
    meta["pending_address_change"] = {"order_sn": order_sn, "new_address": address, "created_at": _now().isoformat()}
    chat.meta_data = meta
    chat.updated_at = _now()
    session.add(chat)


async def _get_pending_address(session: AsyncSession, user_id: int, thread_id: str, order_sn: str) -> Optional[str]:
    pending = await _get_pending_address_state(session, user_id, thread_id, order_sn)
    return str(pending.get("new_address") or "").strip() or None


async def _clear_pending_address(session: AsyncSession, user_id: int, thread_id: str) -> None:
    chat = await _chat_session(session, user_id, thread_id)
    if not chat:
        return
    meta = dict(chat.meta_data or {})
    meta.pop("pending_address_change", None)
    chat.meta_data = meta
    chat.updated_at = _now()
    session.add(chat)


async def _set_pending_action(
    session: AsyncSession,
    user_id: int,
    thread_id: str,
    action: str,
    order_sn: str,
    reason_detail: Optional[str] = None,
) -> None:
    chat = await _chat_session(session, user_id, thread_id)
    if not chat:
        return
    meta = dict(chat.meta_data or {})
    previous = meta.get("pending_action")
    same_flow = (
        isinstance(previous, dict)
        and str(previous.get("action") or "") == action
        and str(previous.get("order_sn") or "").upper() == order_sn.upper()
    )
    state = dict(previous) if same_flow else {}
    state.update({"action": action, "order_sn": order_sn, "created_at": state.get("created_at") or _now().isoformat()})
    if reason_detail:
        state["reason_detail"] = reason_detail.strip()
    meta["pending_action"] = state
    chat.meta_data = meta
    chat.updated_at = _now()
    session.add(chat)

async def _get_pending_action_state(session: AsyncSession, user_id: int, thread_id: str, order_sn: str) -> dict:
    chat = await _chat_session(session, user_id, thread_id)
    pending = (chat.meta_data or {}).get("pending_action") if chat else None
    if isinstance(pending, dict) and str(pending.get("order_sn", "")).upper() == order_sn.upper():
        return dict(pending)
    return {}


async def _get_pending_action(session: AsyncSession, user_id: int, thread_id: str, order_sn: str) -> Optional[str]:
    pending = await _get_pending_action_state(session, user_id, thread_id, order_sn)
    action = str(pending.get("action") or "").strip()
    return action or None

async def _clear_pending_action(session: AsyncSession, user_id: int, thread_id: str) -> None:
    chat = await _chat_session(session, user_id, thread_id)
    if not chat:
        return
    meta = dict(chat.meta_data or {})
    meta.pop("pending_action", None)
    chat.meta_data = meta
    chat.updated_at = _now()
    session.add(chat)

async def _set_pending_flow_switch(session: AsyncSession, user_id: int, thread_id: str, from_action: str, to_action: str, order_sn: str) -> None:
    chat = await _chat_session(session, user_id, thread_id)
    if not chat:
        return
    meta = dict(chat.meta_data or {})
    meta["pending_flow_switch"] = {"from": from_action, "to": to_action, "order_sn": order_sn, "created_at": _now().isoformat()}
    chat.meta_data = meta
    chat.updated_at = _now()
    session.add(chat)


async def _get_pending_flow_switch(session: AsyncSession, user_id: int, thread_id: str, order_sn: str) -> Optional[dict]:
    chat = await _chat_session(session, user_id, thread_id)
    pending = (chat.meta_data or {}).get("pending_flow_switch") if chat else None
    if isinstance(pending, dict) and str(pending.get("order_sn", "")).upper() == order_sn.upper():
        return pending
    return None


async def _clear_pending_flow_switch(session: AsyncSession, user_id: int, thread_id: str) -> None:
    chat = await _chat_session(session, user_id, thread_id)
    if not chat:
        return
    meta = dict(chat.meta_data or {})
    meta.pop("pending_flow_switch", None)
    chat.meta_data = meta
    chat.updated_at = _now()
    session.add(chat)


def _after_sales_intent_label(intent: str) -> str:
    return AFTER_SALES_INTENT_LABELS.get(intent, intent or "当前流程")

def hydrate_catalog_context(catalog: object) -> object:
    """Upgrade product cards cached by older conversations with current catalog facts."""
    items = catalog.get("items") if isinstance(catalog, dict) else None
    if not isinstance(items, list):
        return catalog
    facts = {str(product.get("id") or ""): product for product in PRESALES_PRODUCTS}
    for item in items:
        if not isinstance(item, dict):
            continue
        product = facts.get(str(item.get("id") or ""))
        if not product:
            product = next((value for value in PRESALES_PRODUCTS if value.get("name") == item.get("name")), None)
        if not product:
            continue
        for key in ("inventory_by_color", "inventory_by_size", "restock_eta_by_color", "restock_eta_by_size"):
            if product.get(key) is not None:
                item[key] = product[key]
    return catalog


def _find_presales_product_by_id(product_id: str) -> Optional[dict]:
    return next((item for item in PRESALES_PRODUCTS if item.get("id") == product_id), None)


def _find_presales_product_by_name(name: str) -> Optional[dict]:
    cleaned = name.strip()
    return next((item for item in PRESALES_PRODUCTS if item["name"] in cleaned or cleaned in item["name"]), None)


def _parse_presales_spec_choice(text: str, product: dict) -> tuple[Optional[str], Optional[str]]:
    cleaned = re.sub(r"\s+", "", text).upper()
    color: Optional[str] = None
    size: Optional[str] = None
    for option in product.get("colors") or []:
        if option and option.upper() in cleaned:
            color = option
            break
    size_options = sorted([str(item) for item in product.get("sizes") or []], key=len, reverse=True)
    for option in size_options:
        normalized = re.sub(r"\s+", "", option).upper()
        if not normalized:
            continue
        if cleaned == normalized or normalized in cleaned:
            size = option
            break
    return color, size


def _looks_like_presales_spec_choice(text: str, product: dict) -> bool:
    color, size = _parse_presales_spec_choice(text, product)
    if color or size:
        return True
    cleaned = re.sub(r"\s+", "", text).upper()
    return cleaned in {"S", "M", "L", "XL", "XXL", "XXXL", "均码", "标准版"}


async def _set_pending_presales_spec(session: AsyncSession, user_id: int, thread_id: str, product: dict, color: Optional[str] = None, size: Optional[str] = None) -> None:
    chat = await _chat_session(session, user_id, thread_id)
    if not chat:
        return
    meta = dict(chat.meta_data or {})
    product_keys = ("id", "name", "price", "colors", "sizes", "stock_status")
    meta["pending_presales_spec"] = {
        "product_id": product["id"],
        "product_name": product["name"],
        "product": {key: product.get(key) for key in product_keys},
        "color": color,
        "size": size,
        "created_at": _now().isoformat(),
    }
    # Keep a stable product referent after the temporary spec form completes.
    # Later turns commonly omit its name, for example “雾蓝色有货吗”.
    catalog = meta.get("last_catalog")
    if isinstance(catalog, dict):
        catalog = dict(catalog)
        catalog["active_product_id"] = product["id"]
        meta["last_catalog"] = catalog
    chat.meta_data = meta
    chat.updated_at = _now()
    session.add(chat)


async def _get_pending_presales_spec(session: AsyncSession, user_id: int, thread_id: str) -> Optional[dict]:
    chat = await _chat_session(session, user_id, thread_id)
    pending = (chat.meta_data or {}).get("pending_presales_spec") if chat else None
    return pending if isinstance(pending, dict) and pending.get("product_id") else None


async def _clear_pending_presales_spec(session: AsyncSession, user_id: int, thread_id: str) -> None:
    chat = await _chat_session(session, user_id, thread_id)
    if not chat:
        return
    meta = dict(chat.meta_data or {})
    meta.pop("pending_presales_spec", None)
    chat.meta_data = meta
    chat.updated_at = _now()
    session.add(chat)


async def _handle_pending_presales_spec(session: AsyncSession, user_id: int, thread_id: str, question: str, pending: dict) -> Optional[str]:
    product = _find_presales_product_by_id(str(pending.get("product_id") or "")) or pending.get("product")
    if not isinstance(product, dict) or not product.get("id"):
        await _clear_pending_presales_spec(session, user_id, thread_id)
        return None
    color, size = _parse_presales_spec_choice(question, product)
    selected_color = color or pending.get("color")
    selected_size = size or pending.get("size")
    await _set_pending_presales_spec(session, user_id, thread_id, product, selected_color, selected_size)

    for dimension, option in (("color", selected_color), ("size", selected_size)):
        if option and _inventory_status(product, dimension, option) == "out_of_stock":
            alternatives = _available_options(product, dimension)
            await _set_pending_presales_spec(
                session, user_id, thread_id, product,
                None if dimension == "color" else selected_color,
                None if dimension == "size" else selected_size,
            )
            label = "颜色" if dimension == "color" else "尺码"
            alternative_text = "、".join(alternatives) or "其他选项"
            return f"{product['name']}的{option}{label}当前缺货，目前{alternative_text}有货。你可以换一个{label}，我再继续帮你确认规格。"

    missing = []
    if not selected_color and len(product.get("colors") or []) > 1:
        missing.append("颜色")
    if not selected_size and len(product.get("sizes") or []) > 1:
        missing.append("尺码")

    if missing:
        current = []
        if selected_color:
            current.append(f"颜色：{selected_color}")
        if selected_size:
            current.append(f"尺码：{selected_size}")
        current_text = "，".join(current) if current else "我还没拿到完整规格"
        options = []
        if "颜色" in missing:
            options.append("可选颜色：" + "、".join(product.get("colors") or []))
        if "尺码" in missing:
            options.append("可选尺码：" + "、".join(product.get("sizes") or []))
        missing_text = "和".join(missing)
        option_text = "；".join(options)
        return f"收到，{product['name']} 先记下：{current_text}。\n\n还差{missing_text}，{option_text}。你再发我一下就行。"

    await _clear_pending_presales_spec(session, user_id, thread_id)
    return (
        f"可以，{product['name']} 我先按 {selected_color} / {selected_size} 帮你确认。"
        f"\n\n当前库存状态：{product['stock_status']}，参考价 ¥{float(product['price']):.2f}。这里先只做规格确认，不会自动下单或支付。"
    )

def _presales_spec_product_from_question(question: str, catalog: object = None) -> Optional[dict]:
    match = re.search(r"选择规格[:：]\s*(.+)", question)
    if not match:
        return None
    requested_name = re.sub(r"\s+", "", match.group(1)).lower()
    product = _find_presales_product_by_name(match.group(1).strip())
    if product:
        return product
    items = catalog.get("items") if isinstance(catalog, dict) else None
    if not isinstance(items, list):
        return None
    return next((
        item for item in items
        if isinstance(item, dict)
        and item.get("id")
        and re.sub(r"\s+", "", str(item.get("name") or "")).lower() in requested_name
    ), None)

def extract_tracking_number(question: str) -> Optional[str]:
    match = re.search(r"(?:退货|寄回|快递|物流|单号)[^A-Z0-9]*(SF|YT|JD|ZTO|STO|YTO|EMS)?([A-Z0-9]{8,24})", question, re.IGNORECASE)
    if match:
        return ((match.group(1) or "") + match.group(2)).upper()
    match = re.search(r"\b[A-Z]{1,4}\d{8,24}\b", question, re.IGNORECASE)
    return match.group(0).upper() if match else None


def _status_label(value: object) -> str:
    raw = getattr(value, "value", value)
    return ORDER_STATUS_LABELS.get(str(raw), str(raw))


def _refund_status_label(value: object) -> str:
    raw = getattr(value, "value", value)
    return REFUND_STATUS_LABELS.get(str(raw), str(raw))


def _order_summary(order: Order) -> str:
    items = "、".join(str(item.get("name", "商品")) for item in order.items)
    return f"{items or '订单商品'}，订单号 {order.order_sn}，实付 ¥{float(order.total_amount):.2f}"


def _order_items_name(order: Order) -> str:
    items = "、".join(str(item.get("name", "商品")) for item in order.items)
    return items or "这件商品"


PRODUCT_QA_PRESETS = {
    "云柔家居服套装": {
        "safety": "这件是贴身衣物，如果你对某些纺织面料、染料或柔顺剂容易过敏，建议先清洗后再穿；皮肤正在起疹、破损或明显不适时，先不要贴身长时间穿。",
        "ingredients": "商品信息里是棉感针织面料，偏柔软亲肤；如果你对具体纤维成分很敏感，建议以商品吊牌成分为准。",
        "usage": "适合居家、睡眠和空调房穿着，版型偏宽松，不是运动压缩或外穿防风款。",
        "care": "建议冷水轻柔机洗，深浅色分开，避免漂白和高温烘干，晾晒时尽量反面晾。",
        "warranty": "衣物类没有电子质保，主要看签收后是否存在破损、错发、尺码问题或商品质量问题。",
    },
    "便携保温杯": {
        "safety": "这款是食品接触级不锈钢内胆。装热水时注意防烫，不建议装碳酸饮料、强酸强碱液体，也不要放进微波炉。",
        "ingredients": "杯身内胆是食品接触级不锈钢，外壳和杯盖为日常杯具配件材质。",
        "usage": "适合通勤、上课和短途外出携带，容量约 500ml。",
        "care": "建议用温水和中性清洁剂清洗，杯盖密封圈可以定期取下清洁并晾干。",
        "warranty": "杯具类通常不涉及电子保修；如果收到后有漏水、变形、异味明显或配件缺失，可以申请售后。",
    },
    "轻量通勤双肩包": {
        "safety": "这款是日常通勤包，正常背负使用即可；如果肩颈容易不适，建议不要长期超重装载。",
        "ingredients": "主体是耐磨织物面料，表面有基础防泼水处理。",
        "usage": "适合通勤、上课和短途出行，可放 13 寸电脑和日常随身物品。",
        "care": "轻微污渍可以用湿布擦拭，避免长时间浸泡、机洗和暴晒。",
        "warranty": "如果收到后有拉链损坏、开线、错发或明显破损，可以提交售后凭证处理。",
    },
    "智能降噪耳机 Pro": {
        "safety": "耳机建议中低音量使用，长时间佩戴注意休息；如果佩戴后耳道不适、皮肤过敏或有炎症，先暂停使用。",
        "ingredients": "耳机主体为电子元件和外壳材料，耳塞/耳罩为贴肤配件材质。",
        "usage": "支持主动降噪、通透模式和蓝牙连接，适合通勤、办公和差旅。",
        "care": "避免进水、重压和高温存放，耳塞或耳罩可定期清洁并保持干燥。",
        "warranty": "电子产品如果出现无法开机、无法连接、单边无声等功能问题，可以按售后流程核实质保。",
    },
    "香氛洗护旅行套装": {
        "safety": "有荨麻疹、湿疹、敏感肌或香精过敏史的人，不建议直接大面积使用。可以先看成分表，并在手臂内侧少量试用；如果正在发作、皮肤破损，或医生提醒避免香精/洗护刺激，建议先不要用。使用中如果刺痛、发红、瘙痒，要立即停用并咨询医生。",
        "ingredients": "这款是清爽花果香调的旅行洗护套装，可能含香精类成分；具体成分以瓶身/外包装成分表为准。",
        "usage": "适合短途出行携带和日常洗护，开封后建议尽快用完并盖紧瓶盖。",
        "care": "建议放在阴凉干燥处，避免阳光直射和高温环境；旅行携带时确认瓶盖拧紧。",
        "warranty": "个人护理类商品拆封使用后通常会影响二次销售；如果有漏液、破损、少件或错发，可以拍照申请售后。",
    },
}

PRODUCT_ATTRIBUTE_PRESETS = {
    "云柔家居服套装": {
        "面料": "棉感针织面料，触感偏柔软，适合居家和睡眠场景",
        "版型": "宽松休闲版型",
        "颜色": "浅绿/雾蓝等柔和色系",
        "洗护": "建议冷水轻柔机洗，深浅色分开洗涤",
        "库存": "M、L 码当前都有现货，主推尺码库存比较充足",
    },
    "便携保温杯": {
        "容量": "约 500ml",
        "材质": "食品接触级不锈钢内胆",
        "功能": "日常保温保冷，适合通勤携带",
        "注意": "不建议放入洗碗机或微波炉",
        "库存": "米白款当前有现货，补货压力不大",
    },
    "轻量通勤双肩包": {
        "材质": "耐磨织物面料，表面有基础防泼水处理",
        "容量": "约 18L，可放 13 寸电脑和日常随身物品",
        "尺寸": "约 42 x 29 x 14 cm",
        "结构": "主仓、电脑隔层、前置小袋和侧袋",
        "适用": "通勤、上课、短途出行",
        "适用人群": "更偏日常通勤和学生使用，青少年及成年人都能背；如果是低龄儿童，尺寸会偏大一些",
        "库存": "黑色当前有现货，日常下单没问题",
    },
    "智能降噪耳机 Pro": {
        "功能": "主动降噪、通透模式、蓝牙连接",
        "续航": "单次约 6 小时，搭配充电盒约 24 小时",
        "适用": "通勤、办公、差旅",
        "注意": "耳机属于精密电子产品，建议避免进水、重压和高温存放",
        "库存": "白色当前还有现货，可以继续下单同款",
    },
    "香氛洗护旅行套装": {
        "规格": "旅行装组合，适合短途出行",
        "香型": "清爽花果香调",
        "适用": "日常洗护和旅行携带",
        "注意": "个人护理类商品拆封使用后通常会影响二次销售",
        "库存": "旅行装当前有现货，短期内不用担心断货",
    },
}


def _product_attrs(item: dict, order: Order) -> tuple[str, dict[str, str]]:
    name = str(item.get("name") or _order_items_name(order))
    attrs = dict(PRODUCT_ATTRIBUTE_PRESETS.get(name, {}))
    catalog_product = _find_presales_product_by_name(name)
    if catalog_product and catalog_product.get("colors"):
        attrs["可选颜色"] = "、".join(str(value) for value in catalog_product["colors"])
    for key in ["spec", "规格", "size", "尺码", "color", "颜色", "material", "材质", "capacity", "容量", "inventory", "库存"]:
        value = item.get(key)
        if value:
            label = {
                "spec": "规格", "size": "尺码", "color": "订单颜色", "颜色": "订单颜色",
                "material": "材质", "capacity": "容量", "inventory": "库存",
            }.get(key, key)
            attrs[label] = str(value)
    attrs.setdefault("单价", f"¥{float(item.get('price') or order.total_amount):.2f}")
    if not attrs:
        attrs = {
            "商品": name,
            "数量": str(item.get("qty") or 1),
            "单价": f"¥{float(item.get('price') or order.total_amount):.2f}",
        }
    return name, attrs


def _extract_body_info(question: str) -> tuple[Optional[float], Optional[float], Optional[str]]:
    height = None
    weight = None
    usual_size = None

    height_match = re.search(r"(?:身高|高)?\s*(1\d{2}|2[0-2]\d)\s*(?:cm|厘米|公分)?", question, re.IGNORECASE)
    if height_match:
        height = float(height_match.group(1))

    kg_match = re.search(r"(?:体重|重)?\s*(\d{2,3}(?:\.\d+)?)\s*(?:kg|公斤|千克)", question, re.IGNORECASE)
    jin_match = re.search(r"(?:体重|重)?\s*(\d{2,3}(?:\.\d+)?)\s*(?:斤)", question)
    if kg_match:
        weight = float(kg_match.group(1))
    elif jin_match:
        weight = float(jin_match.group(1)) / 2

    size_match = re.search(r"(?:平时|常穿|一般穿)?\s*(XS|S|M|L|XL|XXL|XXXL|2XL|3XL|4XL)\b", question, re.IGNORECASE)
    if size_match:
        usual_size = size_match.group(1).upper().replace("2XL", "XXL").replace("3XL", "XXXL")

    return height, weight, usual_size


def _recommend_apparel_size(height: Optional[float], weight: Optional[float], current_size: str, fit: str, name: str) -> str:
    if height is None and weight is None:
        return f"这件 {name} 当前订单里是 {current_size}，{fit}。\n\n如果你想判断是否合身，把身高、体重和平时穿的尺码发我，我可以再帮你估一下。"

    suspicious_weight = weight is not None and (weight < 35 or weight > 140)
    if height is not None and suspicious_weight:
        base = "XL" if height >= 175 else "L" if height >= 165 else "M"
        return (
            f"你写的是身高 {height:.0f}cm、体重 {weight:.0f}kg。体重这个数值看起来不太像成人常见范围，可能少写了一位或单位写错了。\n\n"
            f"先只按身高看，这件 {name} 当前订单里的 {current_size} 可能会偏短或偏小，建议优先看 {base}；如果你实际是 120斤、70kg 这类体重，再发我一下，我可以更准地帮你估。"
        )

    recommended = current_size or "M"
    if height is not None:
        if height < 160:
            recommended = "S"
        elif height < 168:
            recommended = "M"
        elif height < 176:
            recommended = "L"
        elif height < 183:
            recommended = "XL"
        else:
            recommended = "XXL"
    if weight is not None:
        if weight < 50:
            weight_size = "S"
        elif weight < 60:
            weight_size = "M"
        elif weight < 72:
            weight_size = "L"
        elif weight < 85:
            weight_size = "XL"
        else:
            weight_size = "XXL"
        order = ["XS", "S", "M", "L", "XL", "XXL", "XXXL"]
        if weight_size in order and recommended in order:
            recommended = order[max(order.index(weight_size), order.index(recommended))]
        else:
            recommended = weight_size

    facts = []
    if height is not None:
        facts.append(f"身高 {height:.0f}cm")
    if weight is not None:
        facts.append(f"体重 {weight:.0f}kg")
    fact_text = "、".join(facts)
    current_note = f"当前订单里是 {current_size}，" if current_size else ""
    return (
        f"按你提供的{fact_text}来看，这件 {name} {current_note}{fit}。\n\n"
        f"我更建议选 {recommended}。如果你喜欢宽松一点，可以再大一号；如果平时穿衣偏合身，就按 {recommended} 先看。"
    )


def _is_product_follow_up(question: str) -> bool:
    cleaned = re.sub(r"\s+", "", question)
    follow_up_keywords = [
        "同款", "再买", "回购", "还能买吗", "还能下单吗", "现货", "库存", "补货", "还有多少", "还有吗",
        "多少钱", "价格", "售价", "优惠吗", "哪个颜色", "还有什么颜色", "颜色还有吗", "适合送人",
        "适合男生", "适合女生", "适合学生", "适合上班", "适合通勤", "能不能", "可以吗", "咋样",
        "参数", "尺寸", "材质", "面料", "续航", "降噪", "保温", "防水", "怎么用", "怎么洗", "好洗吗",
    ]
    return any(keyword in cleaned for keyword in follow_up_keywords)


def _is_generic_product_request(question: str) -> bool:
    q = question.strip()
    if not q:
        return True
    return any(keyword in q for keyword in ["商品详情", "商品属性", "商品信息", "介绍一下", "详细说说", "这个商品", "这件商品", "当前商品", "看看这个"])


async def _llm_product_answer(order: Order, item: dict, question: str, last_assistant: str = "", conversation_context: str = "") -> Optional[str]:
    try:
        from app.graph.nodes import llm
        from langchain_core.messages import SystemMessage, HumanMessage
    except Exception:
        return None

    name, attrs = _product_attrs(item, order)
    item_lines = [f"- {key}: {value}" for key, value in attrs.items()]
    item_summary = "\n".join(item_lines) if item_lines else "- 暂无更多结构化商品信息"
    order_summary = f"订单状态：{_status_label(order.status)}\n订单实付：¥{float(order.total_amount):.2f}"
    history_summary = last_assistant.strip() or "无"
    prompt = (
        "你是店小服，一名电商 AI 客服。请只回答用户这一次最新追问，"
        "不要重新自我介绍，不要重复上一轮已经解释过的整段内容，不要机械复述商品名。\n"
        "请优先依据给定商品信息回答；如果信息里没有精确答案，也要给出自然、实用、不装懂的答复。\n"
        "如果缺少实时库存、颜色或活动信息，要明确说我这边暂时没有看到实时数据或更细配置，"
        "但可以根据当前订单和已知商品信息给一个合理建议。\n"
        "回复控制在 1 到 2 个短段落，语气自然，像真实电商客服，不要寒暄开场。"
    )
    user_content = (
        f"[商品名称]\n{name}\n\n"
        f"[商品信息]\n{item_summary}\n\n"
        f"[订单信息]\n{order_summary}\n\n"
        f"[最近对话（用于理解指代和已确认的信息）]\n{conversation_context.strip() or history_summary}\n\n"
        f"[用户最新问题]\n{question}"
    )
    try:
        response = await invoke_llm(llm, [
            SystemMessage(content=prompt),
            HumanMessage(content=user_content),
        ], stage="product_answer")
    except Exception:
        return None
    content = str(getattr(response, "content", "") or "").strip()
    if not content:
        return None
    content = re.sub(r"^你好[，,].*?\n+", "", content)
    content = re.sub(r"^我是店小服.*?\n+", "", content)
    return content.strip()




async def _llm_order_context_answer(order: Order, question: str, last_assistant: str = "", conversation_context: str = "") -> Optional[str]:
    try:
        from app.graph.nodes import llm
        from langchain_core.messages import SystemMessage, HumanMessage
    except Exception:
        return None

    items = order.items or []
    item_lines = []
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                item_lines.append(
                    f"- {item.get('name', '商品')} x{item.get('qty', 1)}，单价 ¥{float(item.get('price') or 0):.2f}"
                )
    item_summary = "\n".join(item_lines) or "- 订单商品"
    prompt = (
        "你是店小服，一名电商 AI 客服。用户已经在当前会话中绑定了一笔订单。"
        "请根据订单上下文和用户最新问题自然回答，不要说查不到订单，不要重新自我介绍。"
        "如果用户描述商品漏液、破损、少件、错发、变质、异味、包装破损等售后问题，"
        "先表达理解，再说明需要商品、外包装、快递面单照片来核实；不要直接提交人工审核。"
        "如果是平台不能直接确定的问题，可以给出下一步需要的信息或可选操作。"
        "回复控制在 1 到 3 个短段落，像真实电商客服，不展示技术细节、session、thread、工具名。"
    )
    user_content = (
        f"[订单信息]\n"
        f"订单号：{order.order_sn}\n"
        f"订单状态：{_status_label(order.status)}\n"
        f"实付金额：¥{float(order.total_amount):.2f}\n"
        f"收货地址：{order.shipping_address or '暂无'}\n"
        f"物流单号：{order.tracking_number or '暂无'}\n"
        f"商品：\n{item_summary}\n\n"
        f"[最近对话（用于理解指代和已确认的信息）]\n{conversation_context.strip() or last_assistant.strip() or '无'}\n\n"
        f"[用户最新问题]\n{question}"
    )
    try:
        response = await invoke_llm(llm, [SystemMessage(content=prompt), HumanMessage(content=user_content)], stage="order_context_answer")
    except Exception:
        return None
    content = str(getattr(response, "content", "") or "").strip()
    if not content:
        return None
    content = re.sub(r"^你好[，,].*?\n+", "", content)
    content = re.sub(r"^我是店小服.*?\n+", "", content)
    return content.strip()


async def _llm_general_answer(question: str, conversation_context: str = "") -> Optional[str]:
    cleaned = re.sub(r"\s+", "", question)
    if cleaned in {"你好", "您好", "在吗", "有人吗", "hello", "hi"}:
        return "你好，我是店小服，AI 售后助手。你可以直接问商品、订单、物流、退换货、发票或优惠券问题。"
    try:
        from app.graph.nodes import llm
        from langchain_core.messages import SystemMessage, HumanMessage
    except Exception:
        return None
    prompt = (
        "你是店小服，一名电商 AI 客服。只回答可由店铺客服处理的商品、订单、物流、售后、发票、优惠券、支付和平台服务问题；"
        "不要回答技术、百科、学习、新闻或其他通用知识。若遇到非电商问题，只说明不在客服服务范围，不提供知识解释。"
        "如果需要具体订单才能处理，请简短说明需要用户选择订单。"
        "回复 1 到 2 个短段落，不要说系统没有准备，不展示技术细节。"
        "涉及事实性订单、库存、活动或政策时，只依据给定对话和已知信息；未知就说明需要核实，不要编造。"
    )
    try:
        response = await invoke_llm(llm, [SystemMessage(content=prompt), HumanMessage(content=f"[最近对话]\n{conversation_context.strip() or '无'}\n\n[用户最新问题]\n{question}")], stage="general_answer")
    except Exception:
        return None
    content = str(getattr(response, "content", "") or "").strip()
    return content or None

def _product_attribute_text(item: dict, order: Order, question: str = "") -> str:
    name, attrs = _product_attrs(item, order)
    q = question or ""
    qa = PRODUCT_QA_PRESETS.get(name, {})
    responses: list[str] = []

    def add_response(text: Optional[str]) -> None:
        if text and text not in responses:
            responses.append(text)

    audience_keywords = ["几岁", "多大孩子", "适合谁", "适合什么人", "适合哪类人", "适合学生", "适合成人", "谁背", "孩子背", "小学生", "初中生", "高中生", "成年人"]
    safety_keywords = ["荨麻疹", "过敏", "敏感肌", "湿疹", "皮炎", "皮肤", "哮喘", "禁忌", "安全吗", "安全不", "能用吗", "可以用吗", "可用吗"]
    ingredient_keywords = ["成分", "成分表", "材质", "面料", "什么料", "香精", "酒精", "不锈钢", "内胆", "耳塞", "配件材质"]
    usage_keywords = ["怎么用", "如何用", "使用方法", "用法", "适用场景", "适合干嘛", "可以装", "能装", "装得下", "怎么连接", "蓝牙", "降噪", "保温", "续航多久", "续航多长", "能用多久"]
    care_keywords = ["保养", "保存", "存放", "怎么放", "注意事项", "保质期", "开封"]
    warranty_keywords = ["质保", "保修", "坏了怎么办", "售后", "三包", "退换", "退货", "换货", "漏液", "洒了", "异味", "少了", "破包", "破瓶", "破损"]
    spec_keywords = ["规格", "容量", "大小", "多大", "重量", "尺寸", "参数", "ml", "升", "装多少水", "能装多少水"]
    wash_keywords = ["清洗", "洗护", "怎么洗", "水洗", "机洗", "手洗", "晾晒"]
    size_keywords = ["尺码", "合适", "穿多大", "码数", "什么码", "选什么码", "多大码", "身高", "体重"]

    if any(k in q for k in ["孕妇", "孕期", "哺乳", "儿童", "婴儿", "宝宝"]):
        if name == "香氛洗护旅行套装":
            add_response("它是香氛洗护类商品，可能含香精类成分。孕期、哺乳期或儿童使用前，建议先看瓶身成分表，优先选择明确标注适用人群的产品；如果本身容易过敏或医生有特别提醒，先不要直接使用。")
        else:
            add_response("如果是孕妇、儿童或特殊体质使用，建议先确认材质、成分和适用人群标注，必要时咨询专业人士。")

    if any(k in q for k in audience_keywords):
        audience = attrs.get("适用人群") or attrs.get("适用")
        if name == "轻量通勤双肩包":
            add_response(audience or "更偏通勤和学生日常使用，青少年及成年人背会更合适；如果是低龄儿童，尺寸可能会偏大。")
        elif audience:
            add_response(f"比较适合：{audience}。")

    if any(k in q for k in safety_keywords):
        safety = qa.get("safety")
        if safety:
            add_response(safety)
        else:
            add_response("一般正常使用没问题，但如果有过敏史、皮肤破损、特殊疾病或医生特别提醒，建议先确认商品材质或成分，必要时咨询医生后再用。")

    if any(k in q for k in ["保质期", "有效期", "生产日期", "限用日期", "过期"]):
        if name == "香氛洗护旅行套装":
            add_response("保质期要以瓶身或外包装标注为准，通常会写生产日期、限用日期或批号。开封后建议尽快用完，并放在阴凉干燥处；如果出现明显异味、变色、分层或过期，就不要继续使用。")
        else:
            add_response("有效期或质保信息以商品包装、吊牌或说明书标注为准。")

    if any(k in q for k in ingredient_keywords):
        ingredients = qa.get("ingredients")
        material = attrs.get("面料") or attrs.get("材质")
        if ingredients:
            add_response(f"材质和成分这边我帮你看了：{ingredients}")
        elif material:
            add_response(f"材质是：{material}。")

    if any(k in q for k in usage_keywords):
        if any(k in q for k in ["能装", "可以装", "装得下"]) and not any(k in q for k in ["ml", "升", "装多少水", "能装多少水"]) and attrs.get("容量"):
            size = attrs.get("尺寸")
            detail = f"容量大约 {attrs['容量']}"
            if size:
                detail += f"，尺寸 {size}"
                add_response(f"{detail}。像 13 寸电脑、日常通勤物品和短途随身用品，一般都能放下。")
            else:
                add_response(f"{detail}，日常通勤和短途出门一般够用。")
        if any(k in q for k in ["续航多久", "续航多长", "能用多久"]) and attrs.get("续航"):
            add_response(f"续航大概是：{attrs['续航']}。")
        usage = qa.get("usage") or attrs.get("适用") or attrs.get("功能")
        if usage and not any(k in q for k in ["能装", "可以装", "装得下", "续航多久", "续航多长", "能用多久"]):
            add_response(f"主要使用场景是：{usage}")

    if any(k in q for k in care_keywords):
        care = qa.get("care") or attrs.get("注意")
        if care:
            add_response(f"保存或保养时可以这样处理：{care}")

    if any(k in q for k in warranty_keywords):
        warranty = qa.get("warranty")
        if warranty:
            add_response(f"售后这边要注意：{warranty}")

    if any(k in q for k in ["颜色", "什么色", "色号"]):
        selected_color = attrs.get("订单颜色") or attrs.get("颜色") or "当前订单没有更细的颜色标注"
        available_colors = attrs.get("可选颜色")
        asks_all_colors = any(k in q for k in [
            "全部", "所有", "可选", "有哪些", "都有什么", "都有", "其他颜色", "还有什么颜色",
        ])
        if asks_all_colors and available_colors:
            add_response(f"这款商品全部可选颜色有：{available_colors}。你这笔订单选择的是：{selected_color}。")
        elif asks_all_colors:
            add_response(f"目前商品资料里没有更完整的可选颜色信息；你这笔订单选择的是：{selected_color}。")
        else:
            add_response(f"当前订单颜色是：{selected_color}。")

    if any(k in q for k in ["库存", "现货", "补货", "还有货", "还有多少", "还能买吗", "再买", "同款"]):
        inventory = attrs.get("库存")
        price = attrs.get("单价") or f"¥{float(item.get('price') or order.total_amount):.2f}"
        if inventory:
            add_response(f"库存这边我帮你看了：{inventory}。如果你想再买同款，当前参考价还是 {price}。")
        else:
            add_response(f"我这边暂时没有看到实时库存数字，不过这款目前没有标成缺货；如果你想再买同款，可以继续按当前参考价 {price} 下单。")

    if any(k in q for k in ["多少钱", "价格", "售价", "卖多少钱"]):
        price = attrs.get("单价") or f"¥{float(item.get('price') or order.total_amount):.2f}"
        add_response(f"这款当前参考价是 {price}。如果你想再买同款，我也可以继续帮你看库存和颜色。")

    if any(k in q for k in spec_keywords):
        if any(k in q for k in ["ml", "升", "装多少水", "能装多少水"]) and attrs.get("容量"):
            add_response(f"大约可以装 {attrs['容量']} 的水，日常通勤、上课或者短途出门都够用。")
        else:
            pieces = []
            for key in ["规格", "容量", "尺寸", "重量", "结构", "功能", "续航"]:
                if attrs.get(key):
                    pieces.append(f"{key}：{attrs[key]}")
            if pieces:
                add_response("主要规格是：" + "；".join(pieces) + "。")

    if any(k in q for k in wash_keywords):
        wash = attrs.get("洗护") or attrs.get("注意") or "建议按商品洗标处理，深浅色分开，避免高温烘干。"
        material = attrs.get("面料") or attrs.get("材质")
        prefix = "建议这样清洗："
        if material:
            prefix = f"{material}这类材质建议这样清洗："
        add_response(f"{prefix}{wash}")

    height, weight, _usual_size = _extract_body_info(q)
    if (name == "云柔家居服套装" or attrs.get("尺码") or attrs.get("版型") or height is not None or weight is not None) and any(k in q for k in size_keywords):
        size = attrs.get("尺码") or attrs.get("规格") or "常规尺码"
        fit = attrs.get("版型") or "常规版型"
        add_response(_recommend_apparel_size(height, weight, size, fit, name))

    if any(k in q for k in ["材质", "面料", "成分", "什么料"]) and not any(k in q for k in ingredient_keywords):
        material = attrs.get("面料") or attrs.get("材质") or "订单里暂时没有更细的材质标注"
        add_response(f"材质是：{material}。")

    if responses:
        return "\n\n".join(responses[:3])

    if _is_generic_product_request(q):
        detail = "；".join(f"{key}：{value}" for key, value in attrs.items())
        return f"这件商品的主要信息是：{detail}。你可以继续问我具体的尺码、材质、洗护、库存或使用场景。"

    return ""



def _product_card_payload(products: list[dict]) -> str:
    cards = []
    for product in products[:3]:
        cards.append({
            "id": product["id"],
            "name": product["name"],
            "image": product["image"],
            "price": product["price"],
            "selling_points": product["selling_points"],
            "reason": product.get("reason", "符合你的筛选方向"),
            "colors": product["colors"],
            "sizes": product["sizes"],
            "stock_status": product["stock_status"],
            "inventory_by_color": product.get("inventory_by_color"),
            "inventory_by_size": product.get("inventory_by_size"),
            "restock_eta_by_color": product.get("restock_eta_by_color"),
            "restock_eta_by_size": product.get("restock_eta_by_size"),
        })
    payload = json.dumps({"items": cards}, ensure_ascii=False)
    return f"\n\n[[{PRODUCT_CARD_MARKER}:{payload}]]"


def _presales_score(product: dict, question: str) -> int:
    score = 0
    text = re.sub(r"\s+", "", question)
    category_keywords = {
        "内裤", "家居服", "洗护", "睡衣", "T恤", "短袖", "衬衫", "裤子", "阔腿裤", "风扇", "循环扇", "裙子", "半身裙",
        "防晒衣", "运动鞋", "双肩包", "保温杯", "耳机", "充电宝", "移动电源", "防晒霜", "床品", "四件套", "毛巾", "浴巾", "洗衣液",
    }
    product_keywords = product.get("keywords", [])
    for keyword in product_keywords:
        if keyword and keyword in text:
            score += 3 if keyword in category_keywords else 1
    if any(k in text for k in ["夏天", "凉快", "不闷", "透气", "清爽", "轻薄"]):
        if any(k in product_keywords for k in ["透气", "凉感", "轻薄", "清爽", "速干"]):
            score += 3
    if any(k in text for k in ["敏感", "亲肤", "纯棉", "全棉", "柔软"]):
        if any(k in product_keywords for k in ["纯棉", "全棉", "亲肤", "敏感", "柔软"]):
            score += 2
    if any(k in text for k in ["运动", "跑步", "久走", "久站", "防摩擦"]):
        if any(k in product_keywords for k in ["运动", "跑步", "久走", "久站", "防摩擦", "缓震"]):
            score += 2
    if any(k in text for k in ["通勤", "上班", "办公", "面试"]):
        if any(k in product_keywords for k in ["通勤", "上班", "办公", "面试", "正式"]):
            score += 2
    if any(k in text for k in ["宿舍", "租房", "上学", "学生"]):
        if any(k in product_keywords for k in ["宿舍", "租房", "上学", "书包", "床品", "日用"]):
            score += 2
    if any(k in text for k in ["旅行", "出差", "短途", "便携"]):
        if any(k in product_keywords for k in ["旅行", "出差", "短途", "便携", "快充"]):
            score += 2
    if any(k in text for k in ["送礼", "礼物", "生日"]):
        if product.get("category") in {"耳机", "杯具", "数码配件", "护肤", "床品"}:
            score += 2
    return score


def _presales_query_scope(question: str) -> tuple[set[str], bool]:
    categories: set[str] = set()
    strict = False

    exact_rules = [
        (["防晒霜", "防晒乳", "防晒凝露"], {"护肤"}),
        (["防晒帽", "遮阳帽", "空顶帽", "渔夫帽", "帽子"], {"防晒帽"}),
        (["防晒衣", "防晒外套", "防晒服"], {"防晒衣"}),
        (["内裤", "平角裤"], {"内裤"}),
        (["家居服", "睡衣"], {"家居服"}),
        (["T恤", "短袖"], {"T恤"}),
        (["风扇", "循环扇", "桌面风扇"], {"小家电"}),
        (["衬衫", "上班穿", "面试穿"], {"衬衫"}),
        (["裤子", "长裤", "阔腿裤", "休闲裤"], {"裤装"}),
        (["裙子", "半身裙", "A字裙", "连衣裙"], {"裙装"}),
        (["运动鞋", "休闲鞋", "跑鞋", "鞋子", "鞋"], {"运动鞋"}),
        (["双肩包", "背包", "书包", "电脑包"], {"双肩包"}),
        (["斜挎包", "单肩包", "托特包", "帆布包", "包"], {"双肩包"}),
        (["杯子", "水杯", "保温杯"], {"杯具"}),
        (["耳机", "蓝牙耳机", "降噪耳机"], {"耳机"}),
        (["充电宝", "移动电源"], {"数码配件"}),
        (["充电器", "苹果充电", "iphone充电", "type-c充电"], {"充电器"}),
        (["床品", "四件套", "床单", "被套"], {"床品"}),
        (["毛巾", "浴巾", "洗衣液", "家清", "清洁用品", "日用品"], {"家清日用"}),
        (["洗护", "洗发", "沐浴", "旅行装"], {"洗护"}),
    ]
    for keywords, target_categories in exact_rules:
        if any(k in question for k in keywords):
            categories.update(target_categories)
            strict = True
            break

    if strict:
        return categories, True

    if any(k in question for k in ["防晒", "遮阳", "户外防晒", "防晒装备"]):
        categories.update({"防晒衣", "防晒帽", "护肤"})
    if "上衣" in question:
        categories.update({"T恤", "衬衫", "防晒衣"})
    if any(k in question for k in ["宿舍", "租房", "上学", "学生"]):
        categories.update({"床品", "家清日用", "杯具", "双肩包", "洗护"})
    if any(k in question for k in ["出差", "旅行", "短途", "便携"]):
        categories.update({"数码配件", "洗护", "双肩包", "杯具", "耳机"})
    if any(k in question for k in ["通勤", "上班", "办公", "面试"]):
        categories.update({"衬衫", "T恤", "裤装", "裙装", "双肩包", "杯具", "耳机", "数码配件"})
    if any(k in question for k in ["送礼", "礼物", "生日"]):
        categories.update({"耳机", "数码配件", "杯具", "护肤", "床品"})
    return categories, False


def _presales_requested_categories(question: str) -> set[str]:
    categories, _strict = _presales_query_scope(question)
    return categories

def _presales_reason(question: str) -> str:
    if any(k in question for k in ["夏天", "透气", "不闷", "凉快", "清爽", "轻薄"]):
        return "更贴合夏天、透气和轻薄的需求"
    if any(k in question for k in ["纯棉", "全棉", "亲肤", "敏感", "柔软"]):
        return "材质更偏亲肤舒适，适合日常高频使用"
    if any(k in question for k in ["防晒", "户外"]):
        return "更适合户外、防晒或通勤路上的使用场景"
    if any(k in question for k in ["运动", "跑步", "久走", "久站"]):
        return "更适合活动量较多、走路或运动场景"
    if any(k in question for k in ["通勤", "上班", "办公", "面试"]):
        return "更贴合通勤、上班或正式一点的日常需求"
    if any(k in question for k in ["宿舍", "租房", "上学", "学生"]):
        return "更适合宿舍、租房或学生日常使用"
    if any(k in question for k in ["旅行", "出差", "短途", "便携"]):
        return "更适合出差旅行，携带和使用都比较方便"
    if any(k in question for k in ["送礼", "礼物", "生日"]):
        return "价格和实用性都比较适合做礼物"
    return "和你描述的需求匹配度较高"


def _presales_related_categories(requested_categories: set[str], question: str) -> set[str]:
    related = set(requested_categories)
    relation_map = {
        "衬衫": {"T恤", "裤装", "裙装", "防晒衣"},
        "T恤": {"衬衫", "裤装", "防晒衣", "运动鞋"},
        "裤装": {"T恤", "衬衫", "裙装", "运动鞋"},
        "裙装": {"T恤", "衬衫", "裤装", "防晒衣"},
        "防晒衣": {"T恤", "衬衫", "裤装", "护肤"},
        "运动鞋": {"T恤", "裤装", "双肩包"},
        "双肩包": {"运动鞋", "杯具", "数码配件", "耳机"},
        "耳机": {"数码配件", "双肩包", "杯具"},
        "数码配件": {"耳机", "双肩包", "杯具", "洗护"},
        "杯具": {"双肩包", "数码配件", "床品"},
        "床品": {"家清日用", "杯具", "家居服"},
        "家清日用": {"床品", "洗护", "杯具"},
        "洗护": {"护肤", "家清日用", "数码配件"},
        "护肤": {"防晒衣", "洗护", "杯具"},
        "家居服": {"床品", "T恤", "裤装"},
        "内裤": {"家居服", "洗护", "T恤"},
    }
    for category in requested_categories:
        related.update(relation_map.get(category, set()))
    if not requested_categories:
        if any(k in question for k in ["宿舍", "租房", "上学", "学生"]):
            related.update({"床品", "家清日用", "杯具", "双肩包", "洗护"})
        if any(k in question for k in ["出差", "旅行", "短途", "便携"]):
            related.update({"数码配件", "洗护", "双肩包", "杯具", "耳机"})
        if any(k in question for k in ["通勤", "上班", "办公", "面试"]):
            related.update({"衬衫", "T恤", "裤装", "裙装", "双肩包", "杯具", "耳机", "数码配件"})
        if any(k in question for k in ["送礼", "礼物", "生日"]):
            related.update({"耳机", "数码配件", "杯具", "护肤", "床品"})
    return related


def _rank_presales_products(question: str) -> list[dict]:
    ranked: list[tuple[int, dict]] = []
    requested_categories, strict_categories = _presales_query_scope(question)
    exact_candidates = [product for product in PRESALES_PRODUCTS if not requested_categories or product.get("category") in requested_categories]
    related_categories = set(requested_categories) if strict_categories else (_presales_related_categories(requested_categories, question) if requested_categories else set())
    seen_ids: set[str] = set()

    def add_candidate(product: dict, score: int) -> None:
        if score <= 0 or product["id"] in seen_ids:
            return
        item = dict(product)
        item["reason"] = _presales_reason(question)
        ranked.append((score, item))
        seen_ids.add(product["id"])

    for product in exact_candidates:
        score = _presales_score(product, question)
        if requested_categories and product.get("category") in requested_categories:
            score += 5
        add_candidate(product, score)

    if len(ranked) < 3:
        fill_pool = [
            product for product in PRESALES_PRODUCTS
            if product["id"] not in seen_ids and (not related_categories or product.get("category") in related_categories)
        ]
        for product in fill_pool:
            add_candidate(product, _presales_score(product, question))

    if len(ranked) < 3 and requested_categories and not strict_categories:
        for product in PRESALES_PRODUCTS:
            if product["id"] in seen_ids:
                continue
            if product.get("category") in related_categories:
                add_candidate(product, 1)

    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in ranked[:3]]


async def _semantic_presales_products(question: str) -> list[dict]:
    """Let the model rank existing SKUs, then validate every returned ID."""
    try:
        from app.graph.nodes import llm
        from langchain_core.messages import SystemMessage, HumanMessage
    except Exception:
        return []

    catalog_lines = []
    by_id = {str(item["id"]): item for item in PRESALES_PRODUCTS}
    for product_id, item in by_id.items():
        catalog_lines.append("{} | {} | {} | {} | {}".format(
            product_id,
            item.get("name", ""),
            item.get("category", ""),
            "、".join(item.get("selling_points") or []),
            "、".join(item.get("keywords") or []),
        ))
    prompt = (
        "你是电商目录选品器。根据用户的使用场景，从给定目录选择最相关的 1 到 3 个商品。"
        "只能返回目录里真实存在的 id，不得创造商品、价格、库存或属性。"
        "若目录没有合理商品，items 返回空数组。"
        "只输出 JSON：{\"items\":[{\"id\":\"目录ID\",\"reason\":\"与用户场景相关的简短理由\"}]}。"
    )
    try:
        response = await invoke_llm(
            llm,
            [
                SystemMessage(content=prompt),
                HumanMessage(content="[商品目录]\n{}\n\n[用户需求]\n{}".format(chr(10).join(catalog_lines), question)),
            ],
            stage="presales_catalog_selector",
        )
    except Exception:
        return []
    content = str(getattr(response, "content", "") or "").strip()
    match = re.search(r"\{[\s\S]*\}", content)
    if not match:
        return []
    try:
        payload = json.loads(match.group(0))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    selections = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(selections, list):
        return []
    products: list[dict] = []
    seen_ids: set[str] = set()
    for selection in selections[:3]:
        if not isinstance(selection, dict):
            continue
        product_id = str(selection.get("id") or "")
        if product_id not in by_id or product_id in seen_ids:
            continue
        item = dict(by_id[product_id])
        reason = re.sub(r"\s+", " ", str(selection.get("reason") or "")).strip()[:60]
        item["reason"] = reason or "适合你描述的使用场景"
        products.append(item)
        seen_ids.add(product_id)
    return products


def _similar_presales_reply(order: Order, question: str) -> str:
    item = (order.items or [{}])[0] if isinstance(order.items, list) else {}
    source_name = str(item.get("name") or "当前商品") if isinstance(item, dict) else "当前商品"
    products = similar_catalog_products(PRESALES_PRODUCTS, source_name, question)
    if not products:
        return f"我会围绕{source_name}继续帮你找相近款。你也可以告诉我想要的颜色、尺码、材质或预算，我再精准筛选。"
    intro = f"可以。当前这笔订单是“{source_name}”，我按相近的使用场景和穿搭方向帮你筛了这些，不会跳到无关品类。"
    lines = [f"- {product['name']}：{product.get('reason', '和当前商品更接近')}。" for product in products]
    return intro + "\n" + "\n".join(lines) + "\n\n如果你告诉我更偏居家、通勤、凉感还是预算，我可以再缩小到一两款。" + _product_card_payload(products)

async def _presales_reply(question: str) -> str:
    detail_match = re.search(r"查看详情[:：]\s*(.+)", question)
    spec_match = re.search(r"选择规格[:：]\s*(.+)", question)
    if detail_match or spec_match:
        name = (detail_match or spec_match).group(1).strip()
        product = next((item for item in PRESALES_PRODUCTS if item["name"] in name or name in item["name"]), None)
        if product:
            colors = "、".join(product.get("colors") or []) or "以页面可选为准"
            sizes = "、".join(product.get("sizes") or []) or "以页面可选为准"
            points = "、".join(product.get("selling_points") or [])
            price = f"¥{float(product['price']):.2f}"
            if spec_match:
                return (
                    f"可以，这款 {product['name']} 现在可选颜色是：{colors}；可选规格/尺码是：{sizes}。"
                    f"\n\n你把想要的颜色和尺码发我，我先帮你确认库存。这里不会自动下单，也不会直接支付。"
                )
            return (
                f"这款 {product['name']} 我帮你看了一下，价格是 {price}，库存状态是：{product['stock_status']}。"
                f"\n\n主要卖点：{points}。适合{product['category']}相关的日常使用场景。需要的话可以继续点“选择规格”，我再帮你确认颜色和尺码。"
            )

    conversation_products = build_demo_products(question, PRESALES_PRODUCTS)
    products = conversation_products or _rank_presales_products(question)
    if not products:
        products = await _semantic_presales_products(question)
    if not products:
        return (
            "我不想根据不够明确的描述随意推荐商品。你可以告诉我想找的品类或场景，"
            "例如双肩包、耳机、保温杯、床品、护肤，或者直接说预算和使用场景；"
            "我会只从店内对应商品里筛选。"
        )
    is_conversation_catalog = bool(conversation_products)
    preference_prompt = ""
    if not any(k in question for k in ["尺码", "大小", "M", "L", "XL", "颜色", "预算", "价格", "纯棉", "冰丝", "莫代尔"]):
        preference_prompt = "\n\n如果你有尺码、颜色、材质或预算偏好，也可以告诉我，我再帮你缩小到更合适的一两款。"
    if is_conversation_catalog and any(k in question for k in ["学习", "考试", "自习"]):
        intro = "可以，学习时更实用的是收纳、专注和补水这几类，我先帮你选了这几款。"
    elif is_conversation_catalog and any(k in question for k in ["演唱会", "音乐节", "看演出", "追星"]):
        intro = "可以，看演唱会通常要兼顾随身收纳、手机续航和排队候场，我按这三个用途帮你选了几款。"
        preference_prompt = "\n\n如果是室内场还是户外音乐节，也可以告诉我预算和场馆携带限制，我再帮你缩小范围。"
    elif is_conversation_catalog:
        intro = "可以，我按你的需求挑了这几款，供你直接比较。"
    elif any(k in question for k in ["包", "背", "斜挎", "托特"]):
        intro = "可以，我先按轻便、好搭和日常携带这个方向帮你筛了几款。"
    elif any(k in question for k in ["风扇", "循环扇", "桌面风扇", "降温"]):
        intro = "可以，我先按夏天降温、宿舍或桌面使用这个方向帮你筛了几款。"
    elif any(k in question for k in ["防晒帽", "遮阳帽", "帽子", "空顶帽", "渔夫帽"]):
        intro = "可以，我先按防晒帽这个品类帮你筛了几款。"
    elif any(k in question for k in ["防晒霜", "防晒乳", "防晒凝露"]):
        intro = "可以，我先按高倍防晒、夏天清爽使用这个方向帮你筛了几款。"
    elif any(k in question for k in ["防晒", "遮阳"]):
        intro = "可以，我先按通勤防晒、夏天户外使用这个方向帮你筛了几款。"
    elif any(k in question for k in ["内裤", "夏天", "透气", "不闷", "凉快", "清爽"]):
        intro = "可以，我先按夏天使用、透气不闷这个方向帮你筛了 3 款。"
    elif any(k in question for k in ["通勤", "上班", "办公", "面试"]):
        intro = "可以，我先按通勤、上班和日常使用这个方向帮你筛了几款。"
    elif any(k in question for k in ["运动", "跑步", "户外", "久走"]):
        intro = "可以，我先按运动、户外或久走使用这个方向帮你筛了几款。"
    elif any(k in question for k in ["宿舍", "租房", "上学", "学生"]):
        intro = "可以，我先按宿舍、租房和学生日常使用这个方向帮你筛了几款。"
    elif any(k in question for k in ["旅行", "出差", "便携"]):
        intro = "可以，我先按出差旅行、方便携带这个方向帮你筛了几款。"
    elif any(k in question for k in ["送礼", "礼物", "生日"]):
        intro = "可以，我先按实用、好送、不容易踩雷这个方向帮你筛了几款。"
    else:
        intro = "可以，我先按你的描述帮你筛了几款更匹配的商品。"
    reason_lines = [f"- {item['name']}：{item.get('reason', '符合你的筛选方向')}。" for item in products]
    return intro + "\n" + "\n".join(reason_lines) + preference_prompt + _product_card_payload(products)

def _days_since_created(order: Order) -> int:
    return max(0, (_now() - order.created_at).days)


def _refund_next_step(intent: str) -> str:
    if intent == "exchange":
        return "换货申请会进入商家处理，确认可换后会生成新的寄回和补发指引。"
    return "接下来需要按页面提示寄回商品；商家确认收货后，退款会原路退回。"




def _manual_check_for_delivered_order(intent: str, order: Order, days: int, amount: float, refund_count: int, question: str) -> tuple[bool, str, str, RiskLevel]:
    if "人工" in question:
        return True, "用户主动要求人工处理", "你希望人工继续处理。如果确认继续申请，我会把订单和诉求交给审核人员核实。", RiskLevel.MEDIUM

    used_keywords = ["用过", "使用过", "拆封", "洗过", "剪标", "影响二次销售"]
    unused_keywords = ["没用过", "没有用过", "没有使用过", "未使用", "未使用过", "未拆封", "没拆封", "没有拆封"]
    if any(k in question for k in used_keywords) and not any(k in question for k in unused_keywords):
        return True, "商品可能已使用，影响二次销售", "你描述里提到商品可能已经使用或拆封，这会影响二次销售，暂时不能自动处理。", RiskLevel.MEDIUM

    if days > 7:
        if intent == "exchange":
            return True, "超过平台换货期限", "我看了一下，这笔订单签收已经超过 7 天，不能直接自动换货。\n\n如果是质量问题、错发，或者商品仍在保修范围内，我可以继续帮你提交人工核实，但是否通过要结合商品实际情况判断。", RiskLevel.HIGH
        if intent == "refund_only":
            return True, "超过自动仅退款处理期限", "我看了一下，这笔订单签收已经超过 7 天，不能直接自动仅退款。\n\n如果存在未收到、少件、破损或商家责任问题，我可以继续帮你提交人工核实。", RiskLevel.HIGH
        return True, "超过七天无理由期限", "我看了一下，这笔订单已经超过签收后 7 天，所以暂时不能直接按七天无理由退货退款处理。", RiskLevel.HIGH

    if amount >= settings.HIGH_RISK_REFUND_AMOUNT:
        action_label = "换货" if intent == "exchange" else "退款"
        return True, f"{action_label}金额超过自动审批范围（¥{amount:.2f}）", f"我看了一下，这笔订单金额是 ¥{amount:.2f}，超过当前自动{action_label}处理范围，需要人工再核实。", RiskLevel.HIGH

    if refund_count >= 3:
        return True, "当前账号近期售后申请较多", "我看了一下，当前账号近期售后申请比较多，系统需要人工再核实风险，暂时不能自动通过。", RiskLevel.MEDIUM

    return False, "", "", RiskLevel.LOW


def _intake_prompt(intent: str, item_name: str) -> str:
    if intent == "exchange":
        return f"可以，我先帮你看 {item_name} 的换货条件。\n\n请告诉我想换成什么规格/颜色、换货原因，以及商品是否已使用或影响二次销售。确认后我再提交换货申请。"
    if intent == "refund_only":
        return f"好的，我先帮你判断能不能仅退款。\n\n请补充一下：商品是否收到、为什么不需要退回、是否有少件/破损照片。信息确认后我再提交。"
    return f"好的，我来帮你处理。看起来你咨询的是 {item_name}。\n\n请确认：商品是否已收到、想办理退货退款还是仅退款、原因是什么，是否需要上传图片凭证。"

def _manual_review_prompt(reason: str, detail: str) -> str:
    if "可以继续帮你提交人工核实" in detail or "人工再核实" in detail:
        return f"{detail}\n\n还要继续申请吗？"
    return f"{detail}\n\n不过我可以继续帮你提交人工核实，最终是否通过需要结合商品实际情况判断。还要继续申请吗？"


def _manual_review_submitted(reason: str, audit_id: int) -> str:
    return (
        "好的，我已经帮你提交人工核实。处理结果会同步到售后记录里，你也可以随时回来查看进度。"
        f"\n\n人工核实中\n原因：{reason}\n当前状态：等待审核\n预计处理：1 个工作日内\n审核编号：#{audit_id}"
    )


def _product_problem_issue(question: str) -> str:
    if any(k in question for k in ["破洞", "开线", "开裂", "裂了"]):
        return "商品破损"
    if any(k in question for k in ["漏液", "漏了", "洒了", "撒了", "瓶子漏", "洗发露漏", "洗发水漏"]):
        return "商品漏液"
    if any(k in question for k in ["少件", "少发", "漏发", "不完整"]):
        return "商品少件"
    if "错发" in question:
        return "商品错发"
    return "商品异常"


def _product_problem_evidence_prompt(item_name: str, question: str) -> str:
    issue = _product_problem_issue(question)
    return (
        f"我明白了，{item_name}出现{issue}，你想办理退货退款。这个情况可以继续处理。"
        "\n\n为了判断是运输破损、商品质量问题还是包装异常，需要先补充商品问题照片、外包装照片和快递面单照片。你上传后，我会继续帮你判断能否直接提交售后、补发/退款，还是需要人工核实。"
    )


def _product_problem_evidence_reminder(item_name: str, question: str) -> str:
    issue = _product_problem_issue(question)
    return (
        f"收到，已确认你是已收货后申请退货退款，原因是{issue}。"
        "\n\n现在还差图片凭证：请上传商品问题照片、外包装照片和快递面单照片。我收到后就继续帮你核实处理方式。"
    )


def _manual_reason_for_order_state(order: Order) -> tuple[str, str, RiskLevel]:
    status = getattr(order.status, "value", order.status)
    status_label = _status_label(order.status)
    if status in {"SHIPPED", "INTERCEPTING"}:
        return (
            "订单尚未签收",
            "我看了一下，这笔订单还在运输中，系统还没有签收记录，所以暂时不能直接按退货退款处理。",
            RiskLevel.MEDIUM,
        )
    if status == "REFUNDING":
        return (
            "退款正在处理中",
            "我看了一下，这笔订单已经有退款流程在处理，暂时不能重复发起新的自动售后。",
            RiskLevel.LOW,
        )
    if status == "CANCELLED":
        return (
            "订单已取消",
            "我看了一下，这笔订单已经取消，不能再按普通退货流程自动处理。",
            RiskLevel.LOW,
        )
    return (
        "系统暂时无法确定适用规则",
        f"我看了一下，这笔订单当前状态是“{status_label}”，暂时无法确定适用哪一类自动售后规则。",
        RiskLevel.MEDIUM,
    )


async def mark_refund_processing(session: AsyncSession, refund: RefundApplication, order: Order, note: str) -> None:
    refund.status = RefundStatus.PROCESSING
    refund.stage = "退款处理中"
    refund.updated_at = _now()
    refund.admin_note = note
    _append_timeline(refund, "退款处理中", note)
    session.add(refund)

    order.status = OrderStatus.REFUNDING
    order.updated_at = _now()
    session.add(order)


async def _find_order(session: AsyncSession, user_id: int, order_sn: str) -> Optional[Order]:
    result = await session.exec(select(Order).where(Order.order_sn == order_sn, Order.user_id == user_id))
    return result.first()


async def _match_order_by_product_reference(session: AsyncSession, user_id: int, question: str) -> Optional[Order]:
    result = await session.exec(
        select(Order).where(Order.user_id == user_id).order_by(Order.updated_at.desc(), Order.created_at.desc(), Order.id.desc())
    )
    candidates = list(result.all())
    text = question.strip()
    best_order: Optional[Order] = None
    best_score = 0

    for order in candidates:
        raw_items = order.items or []
        if not isinstance(raw_items, list):
            continue
        aliases: list[str] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            aliases.append(name)
            aliases.extend(PRODUCT_NAME_ALIASES.get(name, []))
        score = 0
        for alias in aliases:
            if alias and alias in text:
                score = max(score, len(alias))
        if score > best_score:
            best_score = score
            best_order = order

    return best_order


async def _latest_refunds(session: AsyncSession, user_id: int, order_id: Optional[int] = None) -> list[RefundApplication]:
    stmt = select(RefundApplication).where(RefundApplication.user_id == user_id)
    if order_id:
        stmt = stmt.where(RefundApplication.order_id == order_id)
    stmt = stmt.order_by(RefundApplication.created_at.desc())
    result = await session.exec(stmt)
    return list(result.all())


async def _active_refund_for_order(session: AsyncSession, user_id: int, order_id: int) -> Optional[RefundApplication]:
    refunds = await _latest_refunds(session, user_id, order_id)
    return next((refund for refund in refunds if refund.status in ACTIVE_REFUND_STATUSES), None)


async def _create_audit(
    session: AsyncSession,
    user_id: int,
    thread_id: str,
    order: Order,
    refund: Optional[RefundApplication],
    reason: str,
    risk_level: RiskLevel,
    question: str,
) -> int:
    if refund and refund.id:
        existing_result = await session.exec(
            select(AuditLog)
            .where(AuditLog.user_id == user_id, AuditLog.refund_application_id == refund.id, AuditLog.action == AuditAction.PENDING)
            .order_by(AuditLog.created_at.desc())
        )
        existing_audit = existing_result.first()
        if existing_audit and existing_audit.id:
            record_tool_event("create_manual_audit", success=True, order_sn=order.order_sn, confirmed=True, detail="idempotent_reuse")
            return existing_audit.id
    elif order.id:
        existing_result = await session.exec(
            select(AuditLog)
            .where(AuditLog.user_id == user_id, AuditLog.order_id == order.id, AuditLog.action == AuditAction.PENDING)
            .order_by(AuditLog.created_at.desc())
        )
        existing_audit = existing_result.first()
        if existing_audit and existing_audit.id:
            record_tool_event("create_manual_audit", success=True, order_sn=order.order_sn, confirmed=True, detail="idempotent_reuse")
            return existing_audit.id

    audit = AuditLog(
        thread_id=thread_id,
        user_id=user_id,
        order_id=order.id,
        refund_application_id=refund.id if refund else None,
        trigger_reason=reason,
        risk_level=risk_level,
        action=AuditAction.PENDING,
        context_snapshot={
            "user_request": question,
            "order": order.model_dump(mode="json"),
            "refund": refund.model_dump(mode="json") if refund else None,
            "agent_checks": [
                f"订单状态：{_status_label(order.status)}",
                f"距下单/签收参考时间：{_days_since_created(order)} 天",
                f"退款金额：¥{float(order.total_amount):.2f}",
            ],
            "manual_reason": reason,
        },
    )
    session.add(audit)
    await session.flush()
    try:
        notify_admin_audit.delay(audit.id)
    except Exception:
        pass
    try:
        await manager.notify_status_change(thread_id=thread_id, status="WAITING_ADMIN", data={"audit_log_id": audit.id})
    except Exception:
        pass
    record_tool_event("create_manual_audit", success=True, order_sn=order.order_sn, confirmed=True, detail=reason)
    return audit.id or 0


async def _cancel_pending_audits_for_refund(session: AsyncSession, user_id: int, refund: RefundApplication, note: str) -> int:
    if not refund.id:
        return 0
    result = await session.exec(
        select(AuditLog)
        .where(
            AuditLog.user_id == user_id,
            AuditLog.refund_application_id == refund.id,
            AuditLog.action == AuditAction.PENDING,
        )
        .order_by(AuditLog.created_at.desc())
    )
    audits = list(result.all())
    now = _now()
    for audit in audits:
        audit.action = AuditAction.CANCELLED
        audit.admin_comment = note
        audit.reviewed_at = now
        audit.updated_at = now
        meta = dict(audit.decision_metadata or {})
        meta.update({"cancelled_by_user": True, "cancel_reason": note, "cancelled_at": now.isoformat()})
        audit.decision_metadata = meta
        session.add(audit)
    return len(audits)


def _restore_order_after_after_sales_cancel(order: Order) -> None:
    if order.status in [OrderStatus.REFUNDING, "REFUNDING"]:
        order.status = OrderStatus.DELIVERED if order.tracking_number else OrderStatus.PAID
        order.updated_at = _now()


async def create_refund_record(
    session: AsyncSession,
    order: Order,
    user_id: int,
    reason: str,
    status: RefundStatus,
    admin_note: Optional[str] = None,
) -> RefundApplication:
    if order.id:
        active_refund = await _active_refund_for_order(session, user_id, order.id)
        if active_refund:
            record_tool_event("create_after_sales", success=True, order_sn=order.order_sn, confirmed=True, detail="idempotent_reuse")
            return active_refund

    status_label = _refund_status_label(status)
    refund = RefundApplication(
        order_id=order.id,
        user_id=user_id,
        status=status,
        reason_category=RefundReason.OTHER,
        reason_detail=reason,
        refund_amount=float(order.total_amount),
        admin_note=admin_note,
        stage=status_label,
        timeline=json.dumps([_timeline_item(status_label, admin_note or "")], ensure_ascii=False),
    )
    session.add(refund)
    await session.flush()
    record_tool_event("create_after_sales", success=True, order_sn=order.order_sn, confirmed=True, after=str(getattr(status, "value", status)), detail=reason)
    return refund


async def complete_refund(session: AsyncSession, refund: RefundApplication) -> None:
    refund.status = RefundStatus.COMPLETED
    refund.stage = "退款成功"
    refund.updated_at = _now()
    refund.admin_note = refund.admin_note or "退款已原路退回。"
    _append_timeline(refund, "退款成功", refund.admin_note)
    session.add(refund)

    order = await session.get(Order, refund.order_id)
    if order:
        order.status = OrderStatus.REFUNDED
        order.updated_at = _now()
        session.add(order)


async def handle_consumer_message(question: str, user_id: int, thread_id: str, order_sn: Optional[str], intent_override: Optional[str] = None, pending_action_override: str = "") -> Optional[str]:
    # Active catalogue/specification context wins over a stale order binding for this turn.
    catalog_mode = intent_override == "presales"
    if catalog_mode:
        order_sn = None
    if not order_sn and not catalog_mode:
        async with async_session_maker() as session:
            chat = await _chat_session(session, user_id, thread_id)
            if chat and chat.order_sn:
                order_sn = chat.order_sn

    if has_declined(question) and not wants_cancel_after_sales(question) and not _contains_any(question, ["还是换货", "改成换货", "继续换货", "还是退货", "改成退货", "还是退款", "改成退款"]):
        async with async_session_maker() as session:
            pending_action = await _get_pending_action(session, user_id, thread_id, order_sn) if order_sn else None
            # 撤销售后的确认问题中，“不用了／算了”表达的是停止售后，不能只清理对话状态。
            if pending_action != "cancel_after_sales":
                await _clear_pending_address(session, user_id, thread_id)
                await _clear_pending_action(session, user_id, thread_id)
                await session.commit()
                return "好的，这次先不提交。之后还需要处理的话，可以在这段对话里继续找我。"

    visible_question = _visible_question(question, order_sn)
    catalog_context = False
    pending_catalog_spec = False
    catalog_terms: tuple[str, ...] = ()
    if not order_sn:
        async with async_session_maker() as session:
            chat = await _chat_session(session, user_id, thread_id)
            catalog_data = (chat.meta_data or {}).get("last_catalog") if chat else None
            catalog_context = bool(catalog_data)
            pending_catalog_spec = bool((chat.meta_data or {}).get("pending_presales_spec")) if chat else False
            catalog_terms = catalog_context_terms(catalog_data)
    scope_answer = customer_scope_reply(
        visible_question,
        has_order_context=bool(order_sn),
        has_catalog_context=catalog_context,
        has_pending_catalog_spec=pending_catalog_spec,
        catalog_terms=catalog_terms,
        pending_action=pending_action_override or ("modify_address" if intent_override == "modify_address" else ""),
    )
    if scope_answer:
        return scope_answer
    if (
        _contains_any(visible_question, ["别的银行卡", "其他银行卡", "换银行卡", "换卡退款", "指定银行卡", "朋友银行卡", "他人银行卡"])
        or ("银行卡" in visible_question and _contains_any(visible_question, ["退", "退款", "转到", "打到"]))
    ):
        return "退款只能按订单的原支付路径、原金额退回，不能改到朋友或其他银行卡，也不能额外增加退款金额；这笔申请不会自动提交。若原支付账户无法使用，请先联系原支付渠道核实入账方式。"
    intent = intent_override or classify_intent(visible_question)

    if not order_sn and intent in {"general", "product", "product_detail", "presales"}:
        async with async_session_maker() as session:
            chat = await _chat_session(session, user_id, thread_id)
            catalog_answer = catalog_follow_up_answer((chat.meta_data or {}).get("last_catalog") if chat else None, visible_question)
        if catalog_answer:
            return catalog_answer

    if not order_sn:
        async with async_session_maker() as session:
            chat = await _chat_session(session, user_id, thread_id)
            pending_spec = await _get_pending_presales_spec(session, user_id, thread_id)
            catalog = (chat.meta_data or {}).get("last_catalog") if chat else None
            if not pending_spec and isinstance(catalog, dict):
                active_product_id = str(catalog.get("active_product_id") or "").strip()
                active_product = _find_presales_product_by_id(active_product_id) if active_product_id else None
                if active_product and _looks_like_presales_spec_choice(visible_question, active_product):
                    dialog_state = catalog.get("dialog_state") if isinstance(catalog.get("dialog_state"), dict) else {}
                    seed_color = None
                    seed_size = None
                    if str(dialog_state.get("product_id") or "") == active_product_id:
                        option = str(dialog_state.get("option") or "").strip()
                        if dialog_state.get("dimension") == "color" and option in (active_product.get("colors") or []):
                            seed_color = option
                        elif dialog_state.get("dimension") == "size" and option in (active_product.get("sizes") or []):
                            seed_size = option
                    await _set_pending_presales_spec(session, user_id, thread_id, active_product, seed_color, seed_size)
                    pending_spec = await _get_pending_presales_spec(session, user_id, thread_id)
            if pending_spec and isinstance(catalog, dict):
                dialog_state = catalog.get("dialog_state") if isinstance(catalog.get("dialog_state"), dict) else {}
                pending_product_id = str(pending_spec.get("product_id") or "")
                if str(dialog_state.get("product_id") or "") == pending_product_id:
                    pending_product = _find_presales_product_by_id(pending_product_id) or pending_spec.get("product")
                    if isinstance(pending_product, dict):
                        merged_color = pending_spec.get("color")
                        merged_size = pending_spec.get("size")
                        option = str(dialog_state.get("option") or "").strip()
                        if not merged_color and dialog_state.get("dimension") == "color" and option in (pending_product.get("colors") or []):
                            merged_color = option
                        elif not merged_size and dialog_state.get("dimension") == "size" and option in (pending_product.get("sizes") or []):
                            merged_size = option
                        if merged_color != pending_spec.get("color") or merged_size != pending_spec.get("size"):
                            await _set_pending_presales_spec(session, user_id, thread_id, pending_product, merged_color, merged_size)
                            pending_spec = await _get_pending_presales_spec(session, user_id, thread_id)
            product = (_find_presales_product_by_id(str(pending_spec.get("product_id"))) or pending_spec.get("product")) if pending_spec else None
            if pending_spec and isinstance(product, dict) and intent in {"general", "product", "product_detail", "presales"} and (
                _looks_like_presales_spec_choice(visible_question, product) or is_context_ack(visible_question)
            ):
                reply = await _handle_pending_presales_spec(session, user_id, thread_id, visible_question, pending_spec)
                await session.commit()
                if reply:
                    return reply
            product_to_select = _presales_spec_product_from_question(visible_question, catalog)
            if product_to_select:
                await _set_pending_presales_spec(session, user_id, thread_id, product_to_select)
                await session.commit()
                color_options = [str(item) for item in product_to_select.get("colors") or []]
                size_options = [str(item) for item in product_to_select.get("sizes") or []]
                colors = "、".join(color_options) or "以页面选项为准"
                sizes = "、".join(size_options) or "以页面选项为准"
                example = " ".join([*(color_options[:1]), *(size_options[:1])]) or "页面中的颜色和尺码"
                return (
                    f"可以，{product_to_select['name']} 可选颜色：{colors}；可选尺码/规格：{sizes}。"
                    f"\n\n你可以直接回复颜色和尺码，例如“{example}”；我只会帮你确认规格，不会自动下单或支付。"
                )
    if not order_sn and (intent in {"general", "product", "product_detail"} or needs_order(intent)):
        async with async_session_maker() as session:
            matched_order = await _match_order_by_product_reference(session, user_id, visible_question)
            if matched_order:
                chat = await _chat_session(session, user_id, thread_id)
                if chat and chat.order_sn != matched_order.order_sn:
                    chat.order_sn = matched_order.order_sn
                    chat.updated_at = _now()
                    session.add(chat)
                    await session.commit()
        if matched_order:
            order_sn = matched_order.order_sn
            if intent == "general":
                intent = "product_detail"
    if order_sn and intent == "general" and _looks_like_address(visible_question):
        intent = "modify_address"
    if order_sn and intent == "general" and (any(k in visible_question for k in ["几岁", "谁背", "适合谁", "适合什么人", "小学生", "初中生", "高中生", "成年人"]) or _is_product_follow_up(visible_question)):
        intent = "product_detail"
    if order_sn and intent == "product":
        intent = "product_detail"
    if order_sn and has_confirmed(visible_question) and intent in {"general", "product", "policy", "invoice", "coupon", "payment", "order_query", "logistics", "urge_shipping"}:
        intent = "context_confirm"
    if not needs_order(intent) and not (order_sn and intent == "general"):
        if intent == "presales":
            if order_sn and is_similar_recommendation(visible_question):
                async with async_session_maker() as session:
                    order = await _find_order(session, user_id, order_sn)
                if order:
                    return _similar_presales_reply(order, visible_question)
            return await _presales_reply(visible_question)
        policy_answer = answer_policy_question(question)
        if policy_answer:
            return policy_answer
        if intent == "payment":
            return "我可以帮你核对付款、优惠抵扣和退款去向。你先说说遇到的具体情况；如果需要查某笔订单，我会再请你确认订单。"
        if intent == "price_negotiation":
            return "这个我可以帮你看看有没有可用优惠。商品价格通常按页面活动价结算，我不能直接改价；如果有优惠券、满减或售后补偿，会按订单情况展示给你。"
        if intent == "human":
            if _contains_any(visible_question, ["别人", "朋友", "其他用户", "他人"]) and _contains_any(visible_question, ["订单", "地址", "电话", "手机号", "收货"]):
                return "为了保护用户隐私，我不能查询、展示或操作其他人的订单、地址和联系方式。请让订单本人登录自己的账号处理；如涉及纠纷，可由订单本人联系人工客服核实。"
            return "可以，我会帮你转人工处理。先确认一下相关订单，审核人员才能看到完整的订单和售后上下文。"
        if order_sn and intent == "general":
            async with async_session_maker() as session:
                order = await _find_order(session, user_id, order_sn)
                last_assistant = await _last_assistant_text(session, user_id, thread_id)
                conversation_context = await recent_conversation_context(session, user_id, _client_thread_id(user_id, thread_id))
            if order:
                order_answer = await _llm_order_context_answer(order, visible_question, last_assistant, conversation_context)
                if order_answer:
                    return order_answer
        async with async_session_maker() as session:
            conversation_context = await recent_conversation_context(session, user_id, _client_thread_id(user_id, thread_id))
        general_answer = await _llm_general_answer(visible_question, conversation_context)
        if general_answer:
            return general_answer
        return "我收到你的问题了。你可以再补充一下具体商品、订单或遇到的情况，我会继续帮你判断下一步。"

    selected_sn = order_sn or extract_order_sn(question)
    if not selected_sn:
        if intent in {"presales", "product"}:
            return await _presales_reply(visible_question)
        if intent == "product_detail" and not any(k in visible_question for k in ["这个商品", "这件商品", "该商品", "当前商品", "这个", "这件"]):
            return "可以，商品属性、规格、尺码、材质、容量、库存和使用方式都可以直接问我。\n\n如果你想查已经购买的那件商品，先选一下订单，我会按订单里的商品继续说明。"
        return "我先帮你定位一下是哪笔订单。请点输入框左侧的“+”选择订单，或直接发订单号；确认后我会接着处理你的问题。"

    async with async_session_maker() as session:
        pending_address = await _get_pending_address(session, user_id, thread_id, selected_sn)
        pending_state = await _get_pending_action_state(session, user_id, thread_id, selected_sn)
        pending_action = str(pending_state.get("action") or "") or None
        pending_reason = str(pending_state.get("reason_detail") or "").strip()
        if pending_action == "modify_address" and intent != "modify_address":
            await _clear_pending_address(session, user_id, thread_id)
            await _clear_pending_action(session, user_id, thread_id)
            pending_action = None
            pending_reason = ""
            await session.commit()
        last_assistant = await _last_assistant_text(session, user_id, thread_id)
        conversation_context = await recent_conversation_context(session, user_id, _client_thread_id(user_id, thread_id))
        if pending_action == "refund_only" and is_subjective_return_reason(visible_question):
            await _set_pending_action(
                session, user_id, thread_id, "return_refund", selected_sn, reason_detail=visible_question
            )
            await session.commit()
            return (
                "明白了，你是收到商品后因为不喜欢或不合适而不想保留。这个原因不符合仅退款，"
                "更适合办理退货退款。\n\n"
                "我已经把处理方案调整为退货退款；确认后还会核验售后期限和商品状态，不会直接退款。确认按退货退款继续吗？"
            )
        confirmed = (
            has_confirmed(visible_question)
            or _is_soft_confirm(visible_question)
            or (pending_action == "cancel_after_sales" and (has_declined(visible_question) or wants_cancel_after_sales(visible_question)))
            or (
                pending_action == "cancel_order"
                and re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]+", "", visible_question)
                in {"取消吧", "嗯取消吧", "那就取消吧", "帮我取消吧"}
            )
        )
        confirmation_context_intents = {"general", "context_confirm", "product", "product_detail", "presales", "policy", "invoice", "coupon", "payment", "order_query", "logistics", "urge_shipping"}
        if confirmed and pending_action and (intent in confirmation_context_intents or intent == pending_action):
            intent = pending_action
        elif intent == "context_confirm":
            intent = pending_action or _intent_from_confirmation_context(last_assistant) or "order_query"
        if (
            pending_action in AFTER_SALES_INTENTS
            and intent in {"general", pending_action}
            and not confirmed
            and not has_declined(visible_question)
            and _contains_any(last_assistant, ["原因", "说明一下", "商品有问题"])
        ):
            await _set_pending_action(
                session, user_id, thread_id, pending_action, selected_sn, reason_detail=visible_question
            )
            await session.commit()
            return (
                f"好的，原因已记录为：{visible_question}。\n\n"
                f"这次将为你申请{_after_sales_intent_label(pending_action)}，确认提交吗？"
            )
        if intent == "general" and (pending_address or "新的收货地址" in last_assistant or "当前地址" in last_assistant) and _looks_like_address(visible_question):
            intent = "modify_address"
        if pending_address and confirmed:
            intent = "modify_address"
        order = await _find_order(session, user_id, selected_sn)
        if not order:
            return "我没有在当前账号下找到这笔订单。你可以从“我的订单”重新选择一下，我再继续帮你处理。"

        order_refunds = await _latest_refunds(session, user_id, order.id)
        active_refund = next((refund for refund in order_refunds if refund.status in ACTIVE_REFUND_STATUSES), None)
        completed_refund = next(
            (refund for refund in order_refunds if str(getattr(refund.status, "value", refund.status)) == "COMPLETED"),
            None,
        )
        context_intent = _infer_order_follow_up_intent(visible_question, last_assistant, order, pending_address, pending_action, active_refund)
        if context_intent and intent == "general":
            intent = context_intent
        pending_switch = await _get_pending_flow_switch(session, user_id, thread_id, order.order_sn)
        if pending_switch and (has_declined(visible_question) or "暂不切换" in visible_question):
            await _clear_pending_flow_switch(session, user_id, thread_id)
            await session.commit()
            return "好的，先不切换处理类型。前面的信息我会保留，你可以继续把原因、凭证或下一步诉求发给我。"
        if pending_switch and confirmed:
            intent = str(pending_switch.get("to") or intent)
            await _clear_pending_flow_switch(session, user_id, thread_id)
            await _clear_pending_action(session, user_id, thread_id)
        elif pending_action in AFTER_SALES_INTENTS and intent in AFTER_SALES_INTENTS and pending_action != intent and not confirmed:
            await _set_pending_flow_switch(session, user_id, thread_id, pending_action, intent, order.order_sn)
            await session.commit()
            return (
                f"你当前还在{_after_sales_intent_label(pending_action)}流程里，申请还没有正式提交。\n\n"
                f"如果改成{_after_sales_intent_label(intent)}，前面已收集的原因、规格或凭证要求可能要重新确认。确认切换吗？"
            )

        item_name = _order_items_name(order)
        status_label = _status_label(order.status)
        application_reason = pending_reason or visible_question


        if intent == "product_detail":
            item = (order.items or [{}])[0] if isinstance(order.items, list) else {}
            rule_answer = _product_attribute_text(item, order, visible_question)
            if rule_answer:
                return rule_answer
            llm_answer = await _llm_product_answer(order, item, visible_question, last_assistant, conversation_context)
            if llm_answer:
                return llm_answer
            return _product_attribute_text(item, order, "")

        if intent == "after_sales_intake":
            if completed_refund or order.status in [OrderStatus.REFUNDED, "REFUNDED"]:
                return (
                    "这笔订单已经退款完成，不需要再次申请售后。\n\n"
                    "退款记录会保留在“售后记录”中；如果只是想查看商品信息，可以直接继续问我。"
                )
            if order.status in [OrderStatus.PAID, OrderStatus.PENDING, "PAID", "PENDING"]:
                return "这笔订单还没发货，优先可以处理取消订单、修改地址或催发货。\n\n如果你是想退款，我会先给你取消并进入原路退款；如果只是想改地址，可以直接发新地址。"
            if order.status in [OrderStatus.SHIPPED, OrderStatus.INTERCEPTING, "SHIPPED", "INTERCEPTING"]:
                return "这笔订单还在运输中，暂时不能直接退货。\n\n如果是物流很久没更新，我可以帮你创建物流异常工单；如果收到后有破损、少件或错发，再上传凭证处理售后。"
            if order.status in [OrderStatus.REFUNDING, "REFUNDING"]:
                return "这笔订单已经在售后处理中。\n\n你可以查看进度、补充凭证，或者把遇到的问题继续发给我。"
            return "可以处理售后。你想办理退货退款、仅退款、换货，还是商品破损/少件/错发？\n\n告诉我具体原因后，我会按订单状态和平台规则继续判断。"

        if intent == "cancel_after_sales":
            refunds = await _latest_refunds(session, user_id, order.id)
            active_refund = next((refund for refund in refunds if refund.status in ACTIVE_REFUND_STATUSES), None)
            cancellable_statuses = {
                RefundStatus.USER_CONFIRM, RefundStatus.SUBMITTED, RefundStatus.WAITING_RETURN,
                RefundStatus.PENDING, RefundStatus.NEED_INFO, RefundStatus.APPROVED, RefundStatus.PROCESSING,
                "USER_CONFIRM", "SUBMITTED", "WAITING_RETURN", "PENDING", "NEED_INFO", "APPROVED", "PROCESSING",
            }
            if not active_refund:
                return "我查了一下，这笔订单目前没有可以撤销的售后申请。"
            if active_refund.status not in cancellable_statuses:
                return (
                    f"这笔售后当前是“{_refund_status_label(active_refund.status)}”，已经进入后续处理阶段，不能直接撤销。\n\n"
                    "如果确实不想继续处理，我可以帮你联系人工核实是否还能拦截。"
                )
            if not confirmed:
                await _set_pending_action(session, user_id, thread_id, "cancel_after_sales", order.order_sn)
                await session.commit()
                return f"当前售后申请 #{active_refund.id} 状态是“{_refund_status_label(active_refund.status)}”。\n\n确认要撤销这次售后申请吗？"
            previous_status = _refund_status_label(active_refund.status)
            active_refund.status = RefundStatus.CANCELLED
            active_refund.stage = "已取消"
            active_refund.admin_note = f"用户主动撤销售后申请，撤销前状态：{previous_status}。"
            active_refund.updated_at = _now()
            _append_timeline(active_refund, "已取消", f"用户主动撤销，撤销前状态：{previous_status}")
            cancelled_audits = await _cancel_pending_audits_for_refund(session, user_id, active_refund, "用户已撤销售后申请")
            _restore_order_after_after_sales_cancel(order)
            session.add(order)
            session.add(active_refund)
            session.add(Notification(
                user_id=user_id,
                title="售后申请已撤销",
                content=f"申请 #{active_refund.id} 已取消，订单状态已同步更新。",
                target_type="after_sales",
                target_id=str(active_refund.id),
            ))
            await _clear_pending_action(session, user_id, thread_id)
            await session.commit()
            record_tool_event("cancel_after_sales", success=True, order_sn=order.order_sn, confirmed=True, before=previous_status, after="CANCELLED")
            try:
                await manager.notify_after_sales_change(
                    thread_id,
                    after_sales_payload(active_refund),
                    "售后申请已撤销",
                    user_id=user_id,
                )
                await manager.notify_status_change(
                    thread_id=thread_id,
                    status="AFTER_SALES_CANCELLED",
                    data={"refund_application_id": active_refund.id, "order_sn": order.order_sn, "cancelled_audits": cancelled_audits},
                )
            except Exception:
                pass
            audit_note = "待处理的人工审核也已同步撤销，原审核记录会保留。" if cancelled_audits else "原来的售后记录会保留，方便之后查看。"
            return f"已经撤销这次售后申请了。\n\n申请编号 #{active_refund.id} 当前状态是“已取消”，订单状态也已同步更新。{audit_note}"

        if active_refund and (has_confirmed(visible_question) or _is_soft_confirm(visible_question)) and intent in {"general", "context_confirm", "order_query"}:
            return (
                f"这笔售后申请已经提交过了，我不会重复创建。\n\n"
                f"申请编号 #{active_refund.id}，当前进度是“{_refund_status_label(active_refund.status)}”。"
                "你可以继续补充凭证、填写退货物流，或者去售后记录查看时间线。"
            )

        if intent == "order_query":
            if _contains_any(visible_question, ["地址", "收货地", "收件"]):
                return f"这笔订单的收货地址是：{order.shipping_address}。\n\n订单号 {order.order_sn}，目前状态是“{status_label}”。如果你是想修改地址，我也可以继续按订单状态帮你判断。"
            return f"我帮你看了，这笔订单是 {item_name}，实付 ¥{float(order.total_amount):.2f}。\n\n目前状态是“{status_label}”，订单号 {order.order_sn}。你还想继续查物流，还是处理售后？"

        if intent == "price_negotiation":
            price_reply = f"我帮你看了，这笔订单实付 ¥{float(order.total_amount):.2f}。\n\n商品价格按下单时的活动价结算，我不能直接改价；如果你有优惠券、价保或活动差价问题，可以把情况告诉我，我继续帮你核对。"
            if _contains_any(visible_question, PRODUCT_DETAIL_KEYWORDS):
                item = (order.items or [{}])[0] if isinstance(order.items, list) else {}
                product_reply = _product_attribute_text(item, order, visible_question)
                if product_reply:
                    return f"{price_reply}\n\n另外，你刚才问的商品信息这边我也一起帮你看了：{product_reply}"
            return price_reply

        if intent in {"logistics", "urge_shipping"}:
            if order.status in [OrderStatus.PENDING, OrderStatus.PAID, "PENDING", "PAID"]:
                if intent == "urge_shipping":
                    return f"我看这笔订单还在“{status_label}”，暂时没有物流单号。\n\n我可以先帮你提交催发货提醒；如果商家仍未处理，再继续升级为人工跟进。"
                return f"我看这笔订单还没发出，所以现在查不到物流轨迹。\n\n订单状态是“{status_label}”，发货后我会根据运单继续帮你看包裹到哪了。"
            tracking = order.tracking_number or "暂未生成"
            if order.status in [OrderStatus.INTERCEPTING, "INTERCEPTING"]:
                return f"这笔订单当前正在拦截处理中，物流单号是 {tracking}。快递正在核实是否还能拦截；结果确认前不会显示为已取消，有进展会同步到通知和原对话。"
            if order.status in [OrderStatus.DELIVERED, "DELIVERED"]:
                return f"我帮你查到了，这个包裹已经签收。\n\n物流单号是 {tracking}。如果你没有收到，或者商品有少件、破损，可以继续发我情况，我帮你走售后。"
            return f"我帮你查到了，这个包裹目前正在运输中，物流单号是 {tracking}。\n\n最新轨迹显示包裹已从分拨中心发出，预计还需要 1-2 天更新派送信息。需要我继续帮你催一下物流吗？"

        if intent == "after_sales_status":
            refunds = await _latest_refunds(session, user_id, order.id)
            if not refunds:
                return "我查了一下，这笔订单目前还没有售后申请。\n\n如果你想退货、退款、换货，直接告诉我原因，我会按订单状态帮你判断下一步。"
            refund = refunds[0]
            follow_up_reply = _active_refund_follow_up_reply(refund, order, visible_question)
            if follow_up_reply:
                return follow_up_reply
            note = refund.admin_note or "有新进展会同步到售后记录。"
            return f"这笔订单最近一条售后进度是“{_refund_status_label(refund.status)}”。\n\n申请编号 #{refund.id}，{note}"

        if intent == "cancel_interception":
            if order.status not in [OrderStatus.INTERCEPTING, "INTERCEPTING"]:
                await _clear_pending_action(session, user_id, thread_id)
                await session.commit()
                return "这笔订单当前没有正在处理的物流拦截申请，不需要撤销。你可以继续查看物流，或告诉我其他订单问题。"
            if not (has_confirmed(visible_question) or _is_soft_confirm(visible_question)):
                await _set_pending_action(
                    session, user_id, thread_id, "cancel_interception", order.order_sn,
                    reason_detail="用户申请撤销物流拦截",
                )
                await session.commit()
                return (
                    "这笔订单当前处于‘拦截中’。撤销拦截需要人工联系快递核实，"
                    "能否恢复运输以快递实际处理结果为准；确认前订单状态不会改变。\n\n"
                    "确认申请撤销物流拦截吗？"
                )
            reason = "用户申请撤销物流拦截，需人工联系快递确认是否恢复运输"
            audit_id = await _create_audit(
                session, user_id, thread_id, order, None, reason, RiskLevel.MEDIUM, visible_question
            )
            session.add(Notification(
                user_id=user_id,
                title="撤销物流拦截申请已提交",
                content=f"订单 {order.order_sn} 的撤销拦截申请已提交；快递确认前仍保持‘拦截中’。",
                target_type="conversation",
                target_id=thread_id,
            ))
            await _clear_pending_action(session, user_id, thread_id)
            await session.commit()
            return (
                "撤销物流拦截申请已提交。快递确认前，订单仍显示‘拦截中’；"
                "如果撤销成功，会恢复为运输状态并同步到通知和原对话。"
                f"\n\n人工核实中\n原因：{reason}\n当前状态：等待审核"
                f"\n预计处理：1 个工作日内\n审核编号：#{audit_id}"
            )

        if intent == "cancel_order":
            if order.status in [OrderStatus.PENDING, OrderStatus.PAID, "PENDING", "PAID"]:
                if not confirmed:
                    refund_hint = f"，已付款金额 ¥{float(order.total_amount):.2f} 会进入原路退款" if order.status in [OrderStatus.PAID, "PAID"] else ""
                    await _set_pending_action(session, user_id, thread_id, "cancel_order", order.order_sn)
                    await session.commit()
                    return f"可以取消，这笔订单目前还没发货。\n\n取消后我会继续更新订单状态{refund_hint}。确认取消这笔订单吗？"
                if order.status in [OrderStatus.PAID, "PAID"]:
                    refund = await create_refund_record(session, order, user_id, application_reason, status=RefundStatus.PROCESSING, admin_note="未发货订单取消后，退款进入原路退回流程。")
                    await mark_refund_processing(session, refund, order, "未发货订单取消后，退款进入原路退回流程。")
                    record_tool_event("cancel_order", success=True, order_sn=order.order_sn, confirmed=True, before="PAID", after="REFUND_PROCESSING")
                    await _clear_pending_action(session, user_id, thread_id)
                    await session.commit()
                    return f"已为你取消发货并进入退款处理。\n\n申请编号 #{refund.id}，退款会按原支付路径退回；订单状态会先显示“退款处理中”，完成后再更新为“已退款”。"
                order.status = OrderStatus.CANCELLED
                order.updated_at = _now()
                session.add(order)
                await _clear_pending_action(session, user_id, thread_id)
                await session.commit()
                record_tool_event("cancel_order", success=True, order_sn=order.order_sn, confirmed=True, before="PENDING", after="CANCELLED")
                return "订单已经取消。\n\n这笔订单还没有付款，不会产生退款；你可以在我的订单里看到状态更新。"
            reason = "订单已发货或已签收，取消订单需要人工确认是否可拦截物流"
            if not (has_confirmed(visible_question) or _is_soft_confirm(visible_question)):
                await _set_pending_action(session, user_id, thread_id, "cancel_order", order.order_sn)
                await session.commit()
                return "这笔订单已经进入发货/签收流程，平台不能直接取消。\n\n我可以帮你提交人工核实，看是否还能拦截物流。要继续申请吗？"
            await _create_audit(session, user_id, thread_id, order, None, reason, RiskLevel.MEDIUM, question)
            await _clear_pending_action(session, user_id, thread_id)
            await session.commit()
            return "好的，我已经帮你提交人工核实能否拦截物流。\n\n处理结果会在售后记录里更新。"

        if intent == "modify_address":
            if order.status in [OrderStatus.PENDING, OrderStatus.PAID, "PENDING", "PAID"]:
                address_state = await _get_pending_address_state(session, user_id, thread_id, selected_sn)
                pending_address = str(address_state.get("new_address") or "").strip()
                confirmed_address = has_confirmed(visible_question) or _is_soft_confirm(visible_question)

                if confirmed_address:
                    if not pending_address:
                        missing = _missing_shipping_fields(address_state)
                        missing_text = "、".join(missing) or "完整收货信息"
                        return f"现在还不能提交修改，因为还缺：{missing_text}。请把缺少的信息发给我，补齐后我会再次请你确认。"
                    order.shipping_address = pending_address
                    order.updated_at = _now()
                    session.add(order)
                    await _clear_pending_address(session, user_id, thread_id)
                    await _clear_pending_action(session, user_id, thread_id)
                    await session.commit()
                    record_tool_event("modify_address", success=True, order_sn=order.order_sn, confirmed=True, before="unchanged", after="updated")
                    return f"地址已经改好了。\n\n新的收货信息：{pending_address}\n后续发货会按这份信息处理，你在‘我的订单’里也能看到更新。"

                fields = _parse_shipping_contact(visible_question)
                if any(fields.values()):
                    address_state = await _set_pending_address_draft(
                        session, user_id, thread_id, order.order_sn, fields
                    )
                    await _set_pending_action(
                        session, user_id, thread_id, "modify_address", order.order_sn, reason_detail="awaiting_address"
                    )
                    missing = _missing_shipping_fields(address_state)
                    await session.commit()
                    if missing:
                        recorded = []
                        if address_state.get("recipient"):
                            recorded.append(f"收件人：{address_state['recipient']}")
                        if address_state.get("phone"):
                            recorded.append(f"电话：{address_state['phone']}")
                        if address_state.get("address"):
                            recorded.append(f"地址：{address_state['address']}")
                        recorded_text = "；".join(recorded) or "你刚才发送的内容"
                        return f"已记下：{recorded_text}。\n\n还缺{'、'.join(missing)}，请继续补充；补齐后我再让你确认，不会直接修改订单。"
                    complete_address = _format_shipping_contact(address_state)
                    return (
                        f"我先帮你核对完整收货信息。\n\n当前地址：{order.shipping_address}\n"
                        f"新收货信息：{complete_address}\n\n确认无误后回复‘确认修改’，我再提交；如果不想改了，可以回复‘暂不申请’。"
                    )

                await _set_pending_action(
                    session, user_id, thread_id, "modify_address", order.order_sn, reason_detail="awaiting_address"
                )
                await session.commit()
                return (
                    f"可以修改，这笔订单目前还没发货。\n\n当前地址：{order.shipping_address}\n\n"
                    "请发送新的收件人姓名、联系电话和详细地址；我会先整理成确认信息，确认后才提交修改。"
                )
            await _clear_pending_address(session, user_id, thread_id)
            await _clear_pending_action(session, user_id, thread_id)
            await session.commit()
            return "这笔订单已经发出了，平台现在不能直接修改地址。\n\n如果你不需要这个包裹，可以申请物流拦截；如果只是想改派地址，也可以联系物流核实是否支持。"

        if intent == "logistics_issue":
            tracking = order.tracking_number or "暂未生成"
            intercept_requested = "拦截" in visible_question or pending_reason == "package_intercept"
            if intercept_requested:
                if order.status in [OrderStatus.INTERCEPTING, "INTERCEPTING"]:
                    await _clear_pending_action(session, user_id, thread_id)
                    await session.commit()
                    return "这笔订单的物流拦截申请正在处理中。快递正在核实包裹是否仍可拦截，结果确认前不会显示为已取消；有进展会同步到通知和原对话。"
                if order.status in [OrderStatus.DELIVERED, "DELIVERED"]:
                    await _clear_pending_action(session, user_id, thread_id)
                    await session.commit()
                    return "这笔订单已经签收，物流侧无法再拦截。如果商品不需要了，可以从原对话申请退货退款；商品有问题也可以直接上传凭证。"
                if order.status in [OrderStatus.PAID, OrderStatus.PENDING, "PAID", "PENDING"]:
                    await _clear_pending_action(session, user_id, thread_id)
                    await session.commit()
                    return "这笔订单还没有发出，不需要申请物流拦截。你可以直接选择‘取消订单’，确认后再按取消流程处理。"
                if not (has_confirmed(question) or _is_soft_confirm(question)):
                    await _set_pending_action(
                        session, user_id, thread_id, "logistics_issue", order.order_sn,
                        reason_detail="package_intercept",
                    )
                    await session.commit()
                    return (
                        f"这笔订单已经发出，物流单号是 {tracking}。我可以为你提交包裹拦截申请，"
                        "但是否成功要以快递实际处理结果为准，提交后订单状态不会立即变成已取消。\n\n"
                        "确认提交拦截申请吗？"
                    )
                session.add(Notification(
                    user_id=user_id,
                    title="物流拦截申请已提交",
                    content=f"订单 {order.order_sn} 的包裹拦截申请已提交，快递核实结果会继续同步。",
                    target_type="conversation",
                    target_id=thread_id,
                ))
                order.status = OrderStatus.INTERCEPTING
                order.updated_at = _now()
                session.add(order)
                await _clear_pending_action(session, user_id, thread_id)
                await session.commit()
                record_tool_event("intercept_order", success=True, order_sn=order.order_sn, confirmed=True, before="SHIPPED", after="INTERCEPTING")
                try:
                    await manager.notify_status_change(
                        thread_id=thread_id,
                        status="INTERCEPTING",
                        data={
                            "order_sn": order.order_sn,
                            "order_status": "INTERCEPTING",
                            "order_status_label": "拦截中",
                        },
                    )
                except Exception:
                    pass
                return "物流拦截申请已提交，订单当前状态已更新为‘拦截中’。快递会核实包裹是否仍可拦截；结果确认前不会显示为已取消，有进展会同步到通知和原对话。"
            if order.status in [OrderStatus.PAID, OrderStatus.PENDING, "PAID", "PENDING"]:
                if not (has_confirmed(question) or _is_soft_confirm(question)):
                    await _set_pending_action(session, user_id, thread_id, "logistics_issue", order.order_sn)
                    await session.commit()
                    return f"我看了一下，这笔订单还没发货，所以暂时没有物流轨迹。\n\n如果已经超过承诺发货时间，我可以先帮你提交催发货提醒。要继续催一下吗？"
                session.add(Notification(user_id=user_id, title="催发货已提交", content="店小服已为这笔订单提交催发货提醒。", target_type="conversation", target_id=thread_id))
                await _clear_pending_action(session, user_id, thread_id)
                await session.commit()
                return "好的，我已经帮你提交催发货提醒。\n\n商家处理后会同步到订单和通知里；如果后续仍然没有发货，可以再回来找我继续升级处理。"
            if not (has_confirmed(question) or _is_soft_confirm(question)):
                await _set_pending_action(session, user_id, thread_id, "logistics_issue", order.order_sn)
                await session.commit()
                return f"我帮你查了这笔订单的物流，单号是 {tracking}。\n\n最新轨迹停在分拨中心，暂时没有新的派送记录。需要的话，我可以帮你创建物流异常工单，让商家和快递侧一起核实。要继续吗？"
            session.add(Notification(user_id=user_id, title="物流异常工单已创建", content=f"订单 {order.order_sn} 的物流异常工单已提交，后续结果会继续同步。", target_type="conversation", target_id=thread_id))
            await _clear_pending_action(session, user_id, thread_id)
            await session.commit()
            return "好的，我已经帮你创建物流异常工单。\n\n接下来会先由商家和快递侧核实包裹位置；如果确认丢件或长期无更新，我会继续帮你处理补发或退款。"

        if intent == "damaged_or_missing":
            if not has_evidence(question):
                if _contains_any(last_assistant, ["商品问题照片", "外包装照片", "快递面单照片"]):
                    return _product_problem_evidence_reminder(item_name, visible_question)
                return _product_problem_evidence_prompt(item_name, visible_question)
            if not (has_confirmed(question) or _is_soft_confirm(question)):
                return _manual_review_prompt(
                    "商品问题需要核验证据",
                    "我看到了你描述的商品异常。这类问题需要结合商品照片、外包装和面单一起核实，暂时不能直接自动通过。",
                )
            refund = await create_refund_record(session, order, user_id, question, status=RefundStatus.PENDING, admin_note="商品异常凭证待人工核实。")
            audit_id = await _create_audit(session, user_id, thread_id, order, refund, "商品问题需要核验证据", RiskLevel.MEDIUM, question)
            await session.commit()
            return _manual_review_submitted("商品问题需要核验证据", audit_id)

        if intent in {"return_refund", "refund_only", "exchange"}:
            if completed_refund or order.status in [OrderStatus.REFUNDED, "REFUNDED"]:
                return "这笔订单已经退款完成，不会重复创建售后申请。你可以在“售后记录”中查看退款详情。"
            if active_refund:
                refund = active_refund
                tracking_number = extract_tracking_number(question)
                if refund.status in [RefundStatus.WAITING_RETURN, "WAITING_RETURN"] and tracking_number:
                    refund.return_tracking_number = tracking_number
                    refund.status = RefundStatus.RETURN_SHIPPING
                    refund.stage = "退货运输中"
                    refund.admin_note = "已收到退货物流单号，等待商家确认收货。"
                    refund.updated_at = _now()
                    _append_timeline(refund, "退货运输中", f"退货单号 {tracking_number}")
                    session.add(refund)
                    await session.commit()
                    return f"收到，我已经记录退货物流单号 {tracking_number}。\n\n现在状态是“退货运输中”。商家确认收货后，退款会进入原路退回流程；你也可以在售后记录里继续查看时间线。"
                follow_up_reply = _active_refund_follow_up_reply(refund, order, visible_question)
                if follow_up_reply:
                    return follow_up_reply
                if refund.status in [RefundStatus.WAITING_RETURN, "WAITING_RETURN"]:
                    return f"这笔退货退款已经提交了，当前还在等待你寄回商品。\n\n申请编号 #{refund.id}。寄出后把退货物流单号发给我，或者去售后记录里填写，我会继续更新进度。"
                return f"这笔订单已经在售后处理中。\n\n申请编号 #{refund.id}，当前进度是“{_refund_status_label(refund.status)}”。你可以在售后记录里继续查看后续变化。"

            if order.status in [OrderStatus.PENDING, OrderStatus.PAID, "PENDING", "PAID"]:
                if not (has_confirmed(question) or _is_soft_confirm(question)):
                    await _set_pending_action(session, user_id, thread_id, "return_refund", order.order_sn)
                    await session.commit()
                    return f"好的，我来帮你处理。\n\n这笔订单还没有发货，可以优先取消订单并原路退款，预计退回 ¥{float(order.total_amount):.2f}。确认按这个方案处理吗？"
                refund = await create_refund_record(session, order, user_id, question, status=RefundStatus.PROCESSING, admin_note="未发货订单取消后，退款进入原路退回流程。")
                await mark_refund_processing(session, refund, order, "未发货订单取消后，退款进入原路退回流程。")
                await _clear_pending_action(session, user_id, thread_id)
                await session.commit()
                return f"这笔订单已经进入退款处理。\n\n申请编号 #{refund.id}，退款会按原支付路径退回。订单状态会先显示“退款处理中”，完成后再更新为“已退款”。"

            if order.status in [OrderStatus.REFUNDED, "REFUNDED"]:
                return "这笔订单已经退款完成，不需要重复提交售后。\n\n如果你对到账路径有疑问，我可以继续帮你核对退款说明。"

            if intent == "exchange" and order.status in [OrderStatus.SHIPPED, OrderStatus.INTERCEPTING, "SHIPPED", "INTERCEPTING"]:
                return (
                    "我理解你是想把当前商品换成黑色，尺码保持不变。\n\n"
                    "这笔订单还在运输中，暂时不能直接发起换货；等签收后你在原对话回复我“申请换成黑色”，"
                    "我会按这次已确认的颜色和尺码继续处理。"
                )

            if order.status not in [OrderStatus.DELIVERED, "DELIVERED"]:
                reason, detail, risk = _manual_reason_for_order_state(order)
                if not (has_confirmed(question) or _is_soft_confirm(question)):
                    return _manual_review_prompt(reason, detail)
                refund = await create_refund_record(session, order, user_id, question, status=RefundStatus.PENDING, admin_note=f"等待人工核实：{reason}")
                audit_id = await _create_audit(session, user_id, thread_id, order, refund, reason, risk, question)
                await session.commit()
                return _manual_review_submitted(reason, audit_id)

            if intent == "refund_only" and is_subjective_return_reason(application_reason):
                await _set_pending_action(
                    session, user_id, thread_id, "return_refund", order.order_sn, reason_detail=application_reason
                )
                await session.commit()
                return (
                    "你已经收到商品，单纯因为不喜欢、不合适或买错，不符合仅退款条件，"
                    "更适合办理退货退款。\n\n"
                    "我先为你切换到退货退款方案；确认后会继续核验售后期限和商品状态。确认继续吗？"
                )

            if intent in {"refund_only", "return_refund", "exchange"} and has_product_problem(application_reason) and not has_evidence(application_reason):
                await _set_pending_action(session, user_id, thread_id, intent, order.order_sn)
                await session.commit()
                if _contains_any(last_assistant, ["商品问题照片", "外包装照片", "快递面单照片"]):
                    return _product_problem_evidence_reminder(item_name, visible_question)
                return _product_problem_evidence_prompt(item_name, visible_question)

            days = _days_since_created(order)
            amount = float(order.total_amount)
            user_refunds = await _latest_refunds(session, user_id)
            needs_manual, manual_reason, detail, risk = _manual_check_for_delivered_order(intent, order, days, amount, len(user_refunds), application_reason)

            if needs_manual:
                if not (has_confirmed(visible_question) or _is_soft_confirm(visible_question)):
                    await _set_pending_action(session, user_id, thread_id, intent, order.order_sn)
                    await session.commit()
                    return _manual_review_prompt(manual_reason, detail)
                refund = await create_refund_record(session, order, user_id, application_reason, status=RefundStatus.PENDING, admin_note=f"等待人工核实：{manual_reason}")
                audit_id = await _create_audit(session, user_id, thread_id, order, refund, manual_reason, risk, question)
                await _clear_pending_action(session, user_id, thread_id)
                await session.commit()
                return _manual_review_submitted(manual_reason, audit_id)

            if not (has_confirmed(visible_question) or _is_soft_confirm(visible_question)):
                await _set_pending_action(session, user_id, thread_id, intent, order.order_sn)
                await session.commit()
                return _intake_prompt(intent, item_name)

            if intent == "refund_only":
                note = "仅退款申请已提交，退款处理中；本次不需要寄回商品。"
                refund = await create_refund_record(session, order, user_id, application_reason, status=RefundStatus.PROCESSING, admin_note=note)
                order.status = OrderStatus.REFUNDING
                order.updated_at = _now()
                session.add(order)
                await _clear_pending_action(session, user_id, thread_id)
                await session.commit()
                return f"仅退款申请已经帮你提交了。\n\n申请编号 #{refund.id}。这次不需要寄回商品，退款会先进入处理流程；到账前订单会显示为“退款处理中”。"

            note = "系统核验通过，等待用户寄回商品。" if intent != "exchange" else "换货申请已提交，等待用户寄回商品。"
            refund = await create_refund_record(session, order, user_id, application_reason, status=RefundStatus.WAITING_RETURN, admin_note=note)
            order.status = OrderStatus.REFUNDING
            order.updated_at = _now()
            session.add(order)
            await _clear_pending_action(session, user_id, thread_id)
            await session.commit()
            if intent == "exchange":
                return f"换货申请已经帮你提交了。\n\n申请编号 #{refund.id}。接下来需要先把商品寄回，商家确认后会安排换货；换货规格或颜色如果还没确认，可以继续发给我。"
            return f"已经帮你提交退货退款申请了。\n\n申请编号 #{refund.id}。接下来需要先把商品寄回，商家确认收货后，退款会原路退回。寄出后把退货物流单号发给我，我会继续更新进度。"

        order_answer = await _llm_order_context_answer(order, visible_question, last_assistant, conversation_context)
        if order_answer:
            return order_answer
        return "我理解你的意思了。这笔订单我已经定位到，但还需要你再补充一点具体情况，我才能继续判断是查商品、查物流，还是办理售后。"

    return None
