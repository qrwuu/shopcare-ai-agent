from app.services.catalog_recommendation import _canonical_catalog_question, catalog_context_terms, catalog_follow_up_answer
from app.services.demo_catalog import build_demo_products
from app.models.order import Order, OrderStatus
from app.services.agent_service import _product_attribute_text, hydrate_catalog_context


def _seeded_products():
    return [
        {"id": "backpack-commute-light", "name": "轻量通勤双肩包", "keywords": ["背包"]},
        {"id": "earphone-anc-pro", "name": "智能降噪耳机 Pro", "keywords": ["耳机"]},
        {"id": "cup-vacuum-500ml", "name": "便携保温杯", "keywords": ["保温杯"]},
        {"id": "bag-summer-crossbody", "name": "轻便夏日斜挎包", "keywords": ["斜挎包"]},
        {"id": "powerbank-slim-10000", "name": "轻薄快充充电宝", "keywords": ["充电宝"]},
        {"id": "fan-desk-quiet", "name": "静音循环桌面风扇", "keywords": ["风扇"]},
    ]


def test_unseen_concrete_product_expands_to_normal_shop_cards():
    cards = build_demo_products("我要一个电饭煲", _seeded_products())
    assert len(cards) == 3
    assert {card["name"] for card in cards} == {"智能预约电饭煲 3L", "迷你多功能电饭煲 2L", "家用大容量电饭煲 4L"}
    assert all(card["stock_status"] == "现货充足" for card in cards)
    assert all("演示" not in str(card) and "模拟" not in str(card) for card in cards)


def test_broad_learning_request_uses_relevant_existing_catalog_not_literal_product_name():
    cards = build_demo_products("给我推荐几个学习用的东西", _seeded_products())
    assert [card["id"] for card in cards] == ["backpack-commute-light", "earphone-anc-pro", "cup-vacuum-500ml"]
    assert all("学习用的东西" not in card["name"] for card in cards)


def test_seeded_product_does_not_get_regenerated_as_catalog_expansion():
    seeded = [{"name": "苹果 20W USB-C 快充充电器", "keywords": ["充电器", "苹果", "快充"]}]
    assert build_demo_products("我要一个苹果充电器", seeded) == []


def test_catalog_detail_accepts_display_name_with_spaces():
    cards = build_demo_products("我要一个电饭煲", _seeded_products())
    answer = catalog_follow_up_answer({"items": cards}, "查看详情: 智能预约电饭煲 3L")
    assert answer is not None
    assert "智能预约电饭煲 3L" in answer
    assert "¥" in answer


def test_catalog_ordinal_price_keeps_same_product_context():
    cards = build_demo_products("我要一个电饭煲", _seeded_products())
    answer = catalog_follow_up_answer({"items": cards}, "第一个多少钱")
    assert answer is not None
    assert "智能预约电饭煲 3L当前参考价是" in answer


def test_concert_scenario_returns_relevant_products_with_specific_reasons():
    cards = build_demo_products("给我推荐几个看演唱会可以用的商品", _seeded_products())
    assert [card["id"] for card in cards] == ["bag-summer-crossbody", "powerbank-slim-10000", "fan-desk-quiet"]
    assert "票证" in cards[0]["reason"]
    assert "补电" in cards[1]["reason"]
    assert "降温" in cards[2]["reason"]
    assert all("内裤" not in card["name"] for card in cards)


def test_select_spec_is_not_collapsed_into_generic_detail_reply():
    cards = [{"id": "skirt", "name": "高腰 A 字半身裙", "price": 99, "colors": ["杏色"], "sizes": ["M"]}]
    assert catalog_follow_up_answer({"items": cards}, "选择规格：高腰 A 字半身裙") is None


def test_inventory_followup_uses_active_product_without_repeating_its_name():
    cards = [
        {
            "id": "skirt",
            "name": "高腰 A 字半身裙",
            "price": 99,
            "colors": ["黑色", "杏色", "雾蓝"],
            "sizes": ["S", "M", "L"],
            "stock_status": "杏色和黑色有现货",
        },
        {"id": "other", "name": "通勤衬衫", "colors": ["白色"], "stock_status": "现货充足"},
    ]
    catalog = {"items": cards, "active_product_id": "skirt"}
    answer = catalog_follow_up_answer(catalog, "雾蓝色有货吗")
    assert answer is not None
    assert "高腰 A 字半身裙" in answer
    assert "雾蓝" in answer
    assert "当前缺货" in answer
    assert not answer.startswith("有的")
    assert "通勤衬衫" not in answer



def test_legacy_single_card_context_is_unambiguous_without_active_id():
    card = {
        "id": "skirt",
        "name": "高腰 A 字半身裙",
        "price": 99,
        "colors": ["黑色", "杏色", "雾蓝"],
        "sizes": ["S", "M"],
        "stock_status": "杏色和黑色有现货",
    }
    answer = catalog_follow_up_answer({"items": [card]}, "雾蓝色有货吗")
    assert answer is not None
    assert "雾蓝这个选项，但当前缺货" in answer


def test_bare_spec_value_is_left_to_the_spec_state_machine():
    cards = [{"id": "skirt", "name": "高腰 A 字半身裙", "colors": ["黑色", "雾蓝"], "sizes": ["S", "M"]}]
    catalog = {"items": cards, "active_product_id": "skirt"}
    assert catalog_follow_up_answer(catalog, "黑色") is None
    assert catalog_follow_up_answer(catalog, "M") is None


def test_order_product_color_query_distinguishes_catalog_options_from_selected_variant():
    item = {"name": "轻量通勤双肩包", "price": 159, "color": "黑色"}
    order = Order(
        order_sn="SC-COLOR-01",
        user_id=1,
        status=OrderStatus.DELIVERED,
        total_amount=159,
        items=[item],
        shipping_address="测试地址",
    )

    all_colors = _product_attribute_text(item, order, "查看这款全部可选颜色")
    selected_color = _product_attribute_text(item, order, "这笔订单买的是什么颜色")

    assert "黑色、灰蓝、卡其" in all_colors
    assert "订单选择的是：黑色" in all_colors
    assert selected_color == "当前订单颜色是：黑色。"


def test_inventory_dialog_carries_missing_option_into_restock_followups():
    product = {
        "id": "coat-new",
        "name": "轻量通勤外套",
        "price": 168,
        "colors": ["云朵白", "湖水蓝", "青柠绿"],
        "sizes": ["M", "L", "XL"],
        "stock_status": "云朵白和湖水蓝有货",
        "inventory_by_color": {"云朵白": "in_stock", "湖水蓝": "in_stock", "青柠绿": "out_of_stock"},
        "restock_eta_by_color": {"青柠绿": "预计 5–7 个工作日补货"},
    }
    catalog = {"items": [product], "active_product_id": "coat-new"}

    availability = catalog_follow_up_answer(catalog, "青柠绿还有货吗")
    restock = catalog_follow_up_answer(catalog, "那什么时候能补上")
    elliptical = catalog_follow_up_answer(catalog, "还要等多久")

    assert "青柠绿这个选项，但当前缺货" in availability
    assert "云朵白、湖水蓝有货" in availability
    assert "青柠绿当前缺货" in restock
    assert "预计 5–7 个工作日补货" in restock
    assert "青柠绿当前缺货" in elliptical
    assert catalog["dialog_state"]["option"] == "青柠绿"


def test_catalog_option_entity_does_not_require_generic_color_word():
    product = {
        "id": "bag-new",
        "name": "城市轻行包",
        "colors": ["珊瑚橙", "石墨灰"],
        "sizes": ["标准款"],
        "stock_status": "石墨灰有现货",
    }
    catalog = {"items": [product], "active_product_id": "bag-new"}
    answer = catalog_follow_up_answer(catalog, "珊瑚橙能买不")
    assert "珊瑚橙这个选项，但当前缺货" in answer
    assert "石墨灰有货" in answer


def test_size_inventory_uses_exact_size_tokens_instead_of_substrings():
    product = {
        "id": "shirt-new",
        "name": "基础衬衫",
        "colors": ["白色"],
        "sizes": ["M", "L", "XL", "XXL"],
        "stock_status": "M/L/XL 有货",
    }
    catalog = {"items": [product], "active_product_id": "shirt-new"}
    answer = catalog_follow_up_answer(catalog, "XXL还有吗")
    assert "XXL这个选项，但当前缺货" in answer
    assert "M、L、XL有货" in answer


def test_restock_without_eta_is_honest_instead_of_repeating_stock_template():
    product = {
        "id": "shoe-new",
        "name": "轻便运动鞋",
        "colors": ["白色", "夜蓝"],
        "sizes": ["38", "39"],
        "stock_status": "白色有货",
    }
    catalog = {"items": [product], "active_product_id": "shoe-new"}
    first = catalog_follow_up_answer(catalog, "夜蓝有货吗")
    answer = catalog_follow_up_answer(catalog, "啥时候补货")
    assert "当前缺货" in first
    assert "暂时还没有确认的补货日期" in answer
    assert answer != first


def test_semantic_catalog_plan_is_canonicalized_before_trusted_answering():
    assert _canonical_catalog_question("restock", "青柠绿") == "青柠绿什么时候补货"
    assert _canonical_catalog_question("availability", "XXL") == "XXL还有货吗"
    assert _canonical_catalog_question("other", "青柠绿") is None


def test_catalog_context_terms_are_data_driven():
    catalog = {"items": [{"name": "城市轻行包", "colors": ["珊瑚橙"], "sizes": ["标准款"]}]}
    terms = catalog_context_terms(catalog)
    assert "城市轻行包" in terms
    assert "珊瑚橙" in terms


def test_old_conversation_catalog_is_hydrated_with_current_inventory_facts():
    catalog = {
        "items": [{
            "id": "sunproof-jacket-light",
            "name": "轻薄防晒透气外套",
            "colors": ["米白", "浅蓝", "薄荷绿"],
            "sizes": ["M", "L", "XL"],
            "stock_status": "米白和浅蓝有货",
        }],
        "active_product_id": "sunproof-jacket-light",
    }
    hydrate_catalog_context(catalog)
    first = catalog_follow_up_answer(catalog, "薄荷绿还有货吗")
    answer = catalog_follow_up_answer(catalog, "那什么时候补货")
    assert "当前缺货" in first
    assert "预计 3–5 个工作日补货" in answer
