"""Catalog ranking helpers that keep recommendations anchored to the active product."""
from __future__ import annotations

from typing import Any
import json
import re

CATEGORY_BY_ORDER_PRODUCT = {
    "云柔家居服套装": "家居服",
    "便携保温杯": "杯具",
    "轻量通勤双肩包": "双肩包",
    "智能降噪耳机 Pro": "耳机",
    "香氛洗护旅行套装": "洗护",
}

RELATED_CATEGORIES = {
    "家居服": ("家居服", "T恤", "裤装", "裙装"),
    "T恤": ("T恤", "家居服", "裤装", "衬衫", "裙装"),
    "裤装": ("裤装", "T恤", "衬衫", "裙装", "家居服"),
    "裙装": ("裙装", "T恤", "衬衫", "裤装"),
    "杯具": ("杯具", "双肩包", "数码配件"),
    "双肩包": ("双肩包", "斜挎包", "耳机", "数码配件"),
    "耳机": ("耳机", "数码配件", "双肩包"),
    "洗护": ("洗护", "护肤", "家清日用"),
}

CATEGORY_KEYWORDS = (
    ("家居服", ("家居服", "睡衣", "居家")),
    ("T恤", ("t恤", "短袖", "上衣")),
    ("裤装", ("裤",)),
    ("裙装", ("裙",)),
    ("内裤", ("内衣", "内裤")),
    ("杯具", ("杯",)),
    ("双肩包", ("双肩包", "背包", "书包")),
    ("耳机", ("耳机",)),
    ("洗护", ("洗护", "洗发", "沐浴")),
)


def is_similar_recommendation(question: str) -> bool:
    normalized = "".join(question.split())
    return any(word in normalized for word in ("类似", "相似", "同类", "同款", "搭配", "一样风格", "差不多"))


def similar_catalog_products(
    products: list[dict[str, Any]], source_name: str, question: str, limit: int = 3
) -> list[dict[str, Any]]:
    """Rank static demo catalog items around the product in the active order."""
    source_category = CATEGORY_BY_ORDER_PRODUCT.get(source_name)
    if not source_category:
        source_category = next((item.get("category") for item in products if item.get("name") == source_name), None)
    if not source_category:
        normalized_name = source_name.lower()
        source_category = next((category for category, keywords in CATEGORY_KEYWORDS if any(word in normalized_name for word in keywords)), None)
    allowed = RELATED_CATEGORIES.get(source_category or "", (source_category,) if source_category else ())
    candidates = [item for item in products if item.get("name") != source_name and (not allowed or item.get("category") in allowed)]
    if not candidates:
        candidates = [item for item in products if item.get("name") != source_name]

    normalized = "".join(question.split())
    ranked: list[tuple[int, dict[str, Any]]] = []
    for product in candidates:
        score = 10 if product.get("category") == source_category else 4
        score += sum(2 for keyword in product.get("keywords", []) if keyword and keyword in normalized)
        item = dict(product)
        if product.get("category") == source_category:
            item["reason"] = f"与当前的{source_name}同属{source_category}，风格和使用场景更接近"
        else:
            item["reason"] = f"和{source_name}同属日常穿搭场景，适合一起参考"
        ranked.append((score, item))
    ranked.sort(key=lambda row: (-row[0], str(row[1].get("name", ""))))
    return [item for _, item in ranked[:limit]]


def _option_in_text(option: str, text: str) -> bool:
    option_text = re.sub(r"\s+", "", str(option)).upper()
    normalized = re.sub(r"\s+", "", text).upper()
    if not option_text:
        return False
    if re.fullmatch(r"[A-Z0-9]+", option_text):
        return re.search(rf"(?<![A-Z0-9]){re.escape(option_text)}(?![A-Z0-9])", normalized) is not None
    return option_text in normalized


def _mentioned_option(question: str, options: list[str]) -> str | None:
    return next((option for option in sorted(options, key=len, reverse=True) if _option_in_text(option, question)), None)


def _inventory_status(product: dict[str, Any], dimension: str, option: str) -> str:
    structured = product.get(f"inventory_by_{dimension}")
    if isinstance(structured, dict):
        value = str(structured.get(option) or "").lower()
        if value in {"in_stock", "available", "有货", "现货"}:
            return "in_stock"
        if value in {"out_of_stock", "unavailable", "缺货", "售罄"}:
            return "out_of_stock"

    stock = str(product.get("stock_status") or "")
    same_options = [str(value) for value in product.get("colors" if dimension == "color" else "sizes") or []]
    other_options = [str(value) for value in product.get("sizes" if dimension == "color" else "colors") or []]
    mentioned_same = [value for value in same_options if _option_in_text(value, stock)]
    if mentioned_same:
        return "in_stock" if option in mentioned_same else "out_of_stock"
    if any(_option_in_text(value, stock) for value in other_options):
        return "unknown"
    if any(word in stock for word in ("缺货", "售罄", "无货")):
        return "out_of_stock"
    if any(word in stock for word in ("现货", "有货", "库存充足")):
        return "in_stock"
    return "unknown"


def _available_options(product: dict[str, Any], dimension: str) -> list[str]:
    options = [str(value) for value in product.get("colors" if dimension == "color" else "sizes") or []]
    return [option for option in options if _inventory_status(product, dimension, option) == "in_stock"]


def _remember_dialog_state(
    catalog: object,
    product: dict[str, Any],
    *,
    act: str,
    dimension: str | None = None,
    option: str | None = None,
    availability: str | None = None,
) -> None:
    if not isinstance(catalog, dict):
        return
    product_id = str(product.get("id") or "")
    if product_id:
        catalog["active_product_id"] = product_id
    catalog["dialog_state"] = {
        "product_id": product_id,
        "product_name": str(product.get("name") or ""),
        "act": act,
        "dimension": dimension,
        "option": option,
        "availability": availability,
    }


def _is_restock_query(question: str, state: dict[str, Any], availability: str | None = None) -> bool:
    time_words = ("什么时候", "啥时候", "何时", "多久", "几天", "几号", "到货时间", "还要等", "等多久")
    stock_words = ("有货", "到货", "能买", "能下单", "上架", "库存")
    if "补货" in question or ("补" in question and any(word in question for word in time_words)):
        return True
    if any(word in question for word in time_words) and any(word in question for word in stock_words):
        return True
    return bool(
        any(word in question for word in time_words)
        and (availability == "out_of_stock" or state.get("availability") == "out_of_stock")
        and (state.get("option") or availability == "out_of_stock")
    )


def _restock_eta(product: dict[str, Any], dimension: str, option: str) -> str | None:
    value = product.get(f"restock_eta_by_{dimension}")
    if isinstance(value, dict) and value.get(option):
        return str(value[option])
    value = product.get("restock_eta")
    return str(value) if value else None


def catalog_context_terms(catalog: object) -> tuple[str, ...]:
    items = catalog.get("items") if isinstance(catalog, dict) else None
    if not isinstance(items, list):
        return ()
    values: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        for value in [item.get("name"), *(item.get("colors") or []), *(item.get("sizes") or [])]:
            text = re.sub(r"\s+", "", str(value or "")).lower()
            if text:
                values.add(text)
    return tuple(sorted(values, key=len, reverse=True))


def _canonical_catalog_question(action: str, option: str | None = None) -> str | None:
    target = option or ""
    mapping = {
        "availability": f"{target}还有货吗",
        "restock": f"{target}什么时候补货",
        "list_colors": "这款有哪些颜色",
        "list_sizes": "这款有哪些尺码",
        "price": "这款多少钱",
        "detail": "查看这款详情",
        "arrival_notice": f"{target}到货提醒",
    }
    return mapping.get(action)


async def semantic_catalog_follow_up_answer(catalog: object, question: str) -> str | None:
    """Use the model only to normalize unseen phrasing; facts still come from trusted catalog code."""
    items = catalog.get("items") if isinstance(catalog, dict) else None
    if not isinstance(items, list) or not items:
        return None
    normalized = re.sub(r"\s+", "", question).upper()
    all_options = [
        str(value)
        for item in items if isinstance(item, dict)
        for value in (item.get("colors") or []) + (item.get("sizes") or [])
    ]
    if any(normalized == re.sub(r"\s+", "", option).upper() for option in all_options):
        return None
    state = dict(catalog.get("dialog_state") or {}) if isinstance(catalog, dict) else {}
    compact_items = [
        {
            "id": item.get("id"), "name": item.get("name"),
            "colors": item.get("colors") or [], "sizes": item.get("sizes") or [],
        }
        for item in items[:3] if isinstance(item, dict)
    ]
    prompt = """你是电商商品对话的语义解析器，不回答用户，只输出 JSON。
字段：{"action":"...","product_id":"...或空","option":"...或空"}
action 只能是 availability, restock, list_colors, list_sizes, price, detail, arrival_notice, other。
结合当前商品状态理解代词和省略，例如‘还要等多久’可能是上一轮缺货规格的 restock。
product_id 和 option 只能从给定目录原样选择，不能创造商品、颜色或尺码。与商品无关则 action=other。"""
    payload = {"catalog": compact_items, "dialog_state": state, "user_message": question}
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from app.graph.nodes import llm
        from app.services.agent_telemetry import invoke_llm
        response = await invoke_llm(
            llm,
            [SystemMessage(content=prompt), HumanMessage(content=json.dumps(payload, ensure_ascii=False))],
            stage="catalog_semantic_parser",
        )
        raw = str(getattr(response, "content", "") or "")
        match = re.search(r"\{[\s\S]*\}", raw)
        parsed = json.loads(match.group(0)) if match else {}
    except Exception:
        return None
    action = str(parsed.get("action") or "other")
    if action == "other":
        return None
    product_id = str(parsed.get("product_id") or state.get("product_id") or catalog.get("active_product_id") or "")
    selected = next((item for item in items if isinstance(item, dict) and str(item.get("id") or "") == product_id), None)
    if not selected and len(items) == 1 and isinstance(items[0], dict):
        selected = items[0]
    if not selected:
        return None
    option = str(parsed.get("option") or state.get("option") or "") or None
    valid_options = [str(value) for value in (selected.get("colors") or []) + (selected.get("sizes") or [])]
    if option and option not in valid_options:
        return None
    if isinstance(catalog, dict) and selected.get("id"):
        catalog["active_product_id"] = str(selected["id"])
    canonical = _canonical_catalog_question(action, option)
    return catalog_follow_up_answer(catalog, canonical) if canonical else None


def catalog_follow_up_answer(catalog: object, question: str) -> str | None:
    """Resolve product-card references and carry structured product dialogue state."""
    items = catalog.get("items") if isinstance(catalog, dict) else None
    if not isinstance(items, list) or not items:
        return None
    normalized = "".join(question.split())
    state = dict(catalog.get("dialog_state") or {}) if isinstance(catalog, dict) else {}
    if normalized.startswith(("选择规格:", "选择规格：")):
        return None
    if (("刚才" in normalized or "上次" in normalized) and "推荐" in normalized) or any(word in normalized for word in ("刚才那", "哪几款", "哪一类", "推荐了什么")):
        names = "、".join(str(item.get("name")) for item in items if isinstance(item, dict) and item.get("name"))
        return f"刚才我给你推荐的是：{names}。你想继续看其中哪一款的颜色、尺码、价格或库存？"
    selected: dict[str, Any] | None = next(
        (item for item in items if isinstance(item, dict) and str(item.get("name") or "") and re.sub(r"\s+", "", str(item.get("name"))) in normalized),
        None,
    )
    if not selected:
        ordinal = re.search(r"第\s*([1-3一二三])\s*(个|款|件)?", normalized)
        if ordinal:
            index = {"一": 1, "二": 2, "三": 3}.get(ordinal.group(1), int(ordinal.group(1)) if ordinal.group(1).isdigit() else 0)
            if 1 <= index <= len(items) and isinstance(items[index - 1], dict):
                selected = items[index - 1]
    if not selected and isinstance(catalog, dict):
        active_product_id = str(catalog.get("active_product_id") or state.get("product_id") or "")
        active_product = next(
            (item for item in items if isinstance(item, dict) and str(item.get("id") or "") == active_product_id),
            None,
        )
        active_options = []
        if active_product:
            active_options = [str(value) for value in (active_product.get("colors") or []) + (active_product.get("sizes") or [])]
            if any(normalized.upper() == re.sub(r"\s+", "", option).upper() for option in active_options):
                return None
        contextual_attribute_query = any(
            word in normalized
            for word in (
                "有货", "现货", "缺货", "补货", "库存", "到货", "能买吗",
                "多少钱", "价格", "有哪些颜色", "什么颜色", "可选颜色",
                "有哪些尺码", "什么尺码", "可选尺码", "尺寸是多少", "提醒我",
                "什么时候", "啥时候", "何时", "多久", "还要等", "替代", "别的颜色",
            )
        ) or any(_option_in_text(option, normalized) for option in active_options)
        if active_product and contextual_attribute_query:
            selected = active_product
        elif contextual_attribute_query and len(items) == 1 and isinstance(items[0], dict):
            selected = items[0]
    if not selected:
        return None

    name = str(selected.get("name") or "这款商品")
    colors = [str(value) for value in selected.get("colors") or []]
    sizes = [str(value) for value in selected.get("sizes") or []]
    price = selected.get("price")
    stock = str(selected.get("stock_status") or "库存需要进一步核实")
    requested_color = _mentioned_option(normalized, colors)
    requested_size = _mentioned_option(normalized, sizes)
    state_matches = state.get("product_id") == str(selected.get("id") or "")
    if not requested_color and not requested_size and state_matches:
        previous_option = str(state.get("option") or "")
        if state.get("dimension") == "color" and previous_option in colors:
            requested_color = previous_option
        elif state.get("dimension") == "size" and previous_option in sizes:
            requested_size = previous_option

    dimension = "color" if requested_color else ("size" if requested_size else None)
    requested_option = requested_color or requested_size
    availability = _inventory_status(selected, dimension, requested_option) if dimension and requested_option else None
    restock_query = _is_restock_query(normalized, state, availability)

    if restock_query:
        if not dimension or not requested_option:
            _remember_dialog_state(catalog, selected, act="restock", availability="unknown")
            return f"你想查{name}哪个颜色或尺码的补货时间？告诉我具体选项，我按对应规格核实。"
        _remember_dialog_state(
            catalog, selected, act="restock", dimension=dimension, option=requested_option, availability=availability
        )
        if availability == "in_stock":
            return f"{name}的{requested_option}当前有货，不需要等补货；库存状态是：{stock}。"
        eta = _restock_eta(selected, dimension, requested_option)
        alternatives = [value for value in _available_options(selected, dimension) if value != requested_option]
        alternative_text = f"目前{('、'.join(alternatives))}有货。" if alternatives else "其他规格的库存也需要以页面实时结果为准。"
        if eta:
            return f"{name}的{requested_option}当前缺货，{eta}，具体时间以实际入库为准。{alternative_text}"
        return f"{name}的{requested_option}当前缺货，暂时还没有确认的补货日期。{alternative_text}"

    if any(word in normalized for word in ("到货提醒", "有货提醒", "到了提醒", "补货提醒", "提醒我")):
        _remember_dialog_state(
            catalog, selected, act="arrival_notice", dimension=dimension, option=requested_option, availability=availability
        )
        target = requested_option or "你关注的规格"
        return f"可以关注{name}的{target}到货状态。当前对话不会擅自替你订阅通知，请在商品页开启‘到货提醒’。"

    inventory_query = any(word in normalized for word in ("库存", "现货", "有货", "缺货", "能买吗", "能买", "能下单", "还有吗", "还有没有", "售罄", "卖完"))
    if requested_option and (f"有{requested_option}" in normalized or f"有没有{requested_option}" in normalized):
        inventory_query = True
    if requested_option and inventory_query:
        _remember_dialog_state(
            catalog, selected, act="availability", dimension=dimension, option=requested_option, availability=availability
        )
        alternatives = [value for value in _available_options(selected, dimension) if value != requested_option]
        if availability == "out_of_stock":
            alternative_text = f"目前{('、'.join(alternatives))}有货。" if alternatives else "其他规格库存请以页面实时结果为准。"
            return f"{name}有{requested_option}这个选项，但当前缺货。{alternative_text}你也可以继续问我补货时间。"
        if availability == "in_stock":
            return f"有货，{name}的{requested_option}当前可以选择；库存状态是：{stock}。"
        return f"{name}有{requested_option}这个选项，但现有库存只确认到‘{stock}’，该规格组合需要进一步核实。"

    if any(word in normalized for word in ("颜色", "色号", "什么色", "哪些色")):
        _remember_dialog_state(catalog, selected, act="list_options", dimension="color", option=requested_color)
        if requested_color:
            return f"{name}有{requested_color}这个颜色；全部可选颜色是：{('、'.join(colors))}。当前库存：{stock}。"
        return f"{name}当前可选颜色是：{('、'.join(colors)) or '以页面选项为准'}。{stock}。"
    if any(word in normalized for word in ("尺码", "码", "尺寸", "大小")):
        _remember_dialog_state(catalog, selected, act="list_options", dimension="size", option=requested_size)
        return f"{name}可选规格/尺码是：{('、'.join(sizes)) or '以页面选项为准'}。{stock}。"
    if any(word in normalized for word in ("多少钱", "价格", "预算", "贵", "便宜")):
        _remember_dialog_state(catalog, selected, act="price")
        price_text = f"¥{float(price):.0f}" if price is not None else "以页面为准"
        return f"{name}当前参考价是 {price_text}，{stock}。"
    if inventory_query:
        _remember_dialog_state(catalog, selected, act="availability")
        return f"{name}的库存信息：{stock}。"
    if not any(word in normalized for word in ("详情", "特点", "卖点", "怎么样", "介绍", "看看")):
        return None
    points = "、".join(str(value) for value in selected.get("selling_points") or [])
    _remember_dialog_state(catalog, selected, act="detail")
    price_text = f"¥{float(price):.0f}" if price is not None else "以页面为准"
    return f"你问的是{name}。参考价 {price_text}，主要特点是{points or '以商品详情为准'}；{stock}。"
