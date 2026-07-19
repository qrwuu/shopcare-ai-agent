"""Conversation-aware catalogue expansion for the ShopCare product demo.

The shop can broaden its catalogue during a conversation. These are normal shop
products from a customer perspective; the expansion is scoped to the conversation
only so it never writes temporary SKUs into the shared database.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any


_PURCHASE_PATTERN = re.compile(
    r"(?:我要的是|我想要的是|我要|我想要|想买|买(?:一个|一台|一件|几款)?|推荐(?:几款|一个|一台|一件)?|给我找)"
    r"([^，。！？\s]{1,18})"
)
_GENERIC_REQUEST_WORDS = ("东西", "用品", "好物", "一些", "几个", "几款", "用的", "商品")
_SCENARIO_CATALOG = (
    (("学习", "自习", "备考", "上课"), (
        ("backpack-commute-light", "电脑和书本分区收纳，上课、自习携带更方便"),
        ("earphone-anc-pro", "主动降噪，适合图书馆或宿舍专注学习"),
        ("cup-vacuum-500ml", "容量适中，长时间自习方便补水"),
    )),
    (("演唱会", "音乐节", "看演出", "追星"), (
        ("bag-summer-crossbody", "轻便随身，可放手机、票证和随身小物"),
        ("powerbank-slim-10000", "候场和拍摄时间较长时方便给手机补电"),
        ("fan-desk-quiet", "夏季排队候场时可随身降温"),
    )),
    (("旅行", "出差", "旅游", "短途"), (
        ("backpack-commute-light", "容量适中，衣物和数码用品可以分区收纳"),
        ("travel-wash-set", "旅行装容量，短途携带不占空间"),
        ("powerbank-slim-10000", "路途中方便给手机和耳机补电"),
    )),
    (("运动", "跑步", "健身", "徒步"), (
        ("sneaker-cloud-walk", "缓震透气，适合跑步、健身和久走"),
        ("earphone-open-sport", "开放式佩戴，运动时更稳也能留意环境声音"),
        ("tshirt-coolmax-daily", "速干不易粘身，运动出汗后更清爽"),
    )),
    (("户外", "露营", "郊游", "爬山"), (
        ("sunproof-hat-upf50", "遮阳可调，户外活动携带方便"),
        ("sunscreen-daily-sensitive", "日常户外防晒，肤感相对清爽"),
        ("powerbank-slim-10000", "长时间在外时为手机提供续航"),
    )),
    (("夏天", "高温", "天气热", "降温"), (
        ("fan-desk-quiet", "桌面、宿舍和排队场景都能辅助降温"),
        ("tshirt-coolmax-daily", "凉感速干，炎热天气穿着不易粘身"),
        ("sunscreen-daily-sensitive", "通勤和日常户外可用于防晒"),
    )),
    (("宿舍", "租房"), (
        ("fan-desk-quiet", "体积小，适合宿舍或租房桌面使用"),
        ("earphone-lite-commute", "日常网课和影音使用方便"),
        ("bedding-cotton-set", "基础床品组合，入住时更省心"),
    )),
    (("办公", "通勤", "上班"), (
        ("backpack-commute-light", "带电脑分区，通勤收纳更清楚"),
        ("earphone-anc-pro", "降噪功能适合通勤和开放办公区"),
        ("cup-vacuum-500ml", "通勤携带方便，办公时可保温保冷"),
    )),
    (("送礼", "礼物", "生日"), (
        ("cup-vacuum-500ml", "实用耐用，作为日常礼物不容易闲置"),
        ("earphone-lite-commute", "使用场景广，适合日常通勤娱乐"),
        ("travel-wash-set", "套装完整，包装和使用体验更适合送礼"),
    )),
)


def _normalise(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").lower())


def _requested_product_name(question: str) -> str | None:
    match = _PURCHASE_PATTERN.search(_normalise(question))
    if not match:
        return None
    name = re.sub(r"^(?:一个|一台|一件|几个|几款|个|台|件)", "", match.group(1))
    name = re.sub(r"(?:的|吧|呀|啊)$", "", name)
    return name[:16] if len(name) >= 2 else None


def _matches_seeded_catalog(question: str, seeded_products: list[dict[str, Any]]) -> bool:
    text = _normalise(question)
    for product in seeded_products:
        if _normalise(str(product.get("name") or "")) in text:
            return True
        if any(_normalise(str(keyword)) in text for keyword in product.get("keywords") or []):
            return True
    return False


def _scenario_products(question: str, seeded_products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    text = _normalise(question)
    selections = next((items for aliases, items in _SCENARIO_CATALOG if any(alias in text for alias in aliases)), ())
    if not selections:
        return []
    by_id = {str(item.get("id")): item for item in seeded_products}
    products: list[dict[str, Any]] = []
    for product_id, reason in selections:
        if product_id not in by_id:
            continue
        product = dict(by_id[product_id])
        product["reason"] = reason
        products.append(product)
    return products


def _product_variants(product_name: str, base_price: int) -> tuple[tuple[str, int, list[str]], ...]:
    if "电饭煲" in product_name:
        return (
            ("智能预约电饭煲 3L", base_price, ["24 小时预约", "一键柴火饭", "不粘内胆"]),
            ("迷你多功能电饭煲 2L", base_price - 20, ["适合 1–2 人", "煮饭煲汤两用", "小巧好收纳"]),
            ("家用大容量电饭煲 4L", base_price + 60, ["适合家庭使用", "多种烹饪模式", "可拆洗内盖"]),
        )
    return (
        (f"{product_name} 经典款", base_price, ["日常实用", "品质材质", "现货供应"]),
        (f"{product_name} 轻量款", max(59, base_price - 20), ["轻便易用", "收纳方便", "现货供应"]),
        (f"{product_name} 升级款", base_price + 50, ["功能升级", "使用更舒适", "现货供应"]),
    )


def build_demo_products(question: str, seeded_products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return suitable shop cards for a broad scenario or a new concrete item."""
    if _matches_seeded_catalog(question, seeded_products):
        return []
    scenario_products = _scenario_products(question, seeded_products)
    if scenario_products:
        return scenario_products

    product_name = _requested_product_name(question)
    if not product_name:
        return []
    if any(word in product_name for word in _GENERIC_REQUEST_WORDS):
        return []

    digest = hashlib.sha256(product_name.encode("utf-8")).hexdigest()[:8]
    base_price = 129 + int(digest[:2], 16) % 80
    return [
        {
            "id": f"catalog-{digest}-{index}",
            "name": name,
            "category": "厨房电器" if "电饭煲" in product_name else "精选商品",
            "image": "/product-images/cup-vacuum-500ml.svg",
            "price": float(price),
            "selling_points": points,
            "colors": ["白色", "深灰"],
            "sizes": ["标准款"],
            "stock_status": "现货充足",
            "reason": "根据你的需求为你挑选",
            "source": "conversation_catalog",
        }
        for index, (name, price, points) in enumerate(_product_variants(product_name, base_price), start=1)
    ]
