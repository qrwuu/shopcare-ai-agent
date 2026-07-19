import pytest

from app.services.customer_scope import customer_scope_reply, is_product_recommendation_request
from app.services.agent_service import _is_soft_confirm, _missing_shipping_fields, _parse_shipping_contact, classify_intent, needs_order, wants_cancel_after_sales, is_subjective_return_reason
from app.services.policy_knowledge import answer_policy_question, is_policy_question


@pytest.mark.parametrize(
    "question",
    [
        "大模型的定义是什么",
        "自然语言处理的定义是啥",
        "卷积神经网络是怎么工作的",
        "Transformer 模型有什么用",
        "Python 怎么写爬虫",
        "机器学习和深度学习有什么区别",
        "量子力学是什么",
        "今天股票能买吗",
        "帮我写一份论文摘要",
    ],
)
def test_unseen_general_knowledge_is_default_denied(question: str):
    answer = customer_scope_reply(question)
    assert answer is not None
    assert "只能处理店内商品、订单、物流、售后、支付和平台服务" in answer
    assert "定义是" not in answer


@pytest.mark.parametrize(
    "question",
    [
        "七天无理由退款定义",
        "内衣拆封后能不能退",
        "退货运费由谁承担",
        "退款多久原路到账",
        "少件需要上传哪些凭证",
        "发货以后还能取消吗",
        "修改收货地址有什么限制",
        "价保差价怎么算",
        "什么情况会转人工审核",
        "平台如何保护用户隐私",
        "仅退款和退货退款有什么区别",
    ],
)
def test_public_policy_consultation_needs_no_order_and_no_llm(question: str):
    assert customer_scope_reply(question) is None
    assert is_policy_question(question)
    assert classify_intent(question) == "policy"
    assert not needs_order("policy")
    answer = answer_policy_question(question)
    assert answer
    assert "请选择订单" not in answer
    assert "不在客服服务范围" not in answer


@pytest.mark.parametrize(
    "question,expected_intent",
    [
        ("我要申请退款", "return_refund"),
        ("帮我取消这个订单", "cancel_order"),
        ("我要修改收货地址", "modify_address"),
    ],
)
def test_policy_topics_with_explicit_execution_still_require_order(question: str, expected_intent: str):
    assert not is_policy_question(question)
    assert classify_intent(question) == expected_intent
    assert needs_order(expected_intent)


def test_wellbeing_recommendation_never_turns_into_unrelated_cards():
    assert customer_scope_reply("给我推荐几款我学习压力大可以用到的东西") is None


@pytest.mark.parametrize(
    "question",
    [
        "推荐一个上学用的双肩包，预算 200",
        "通勤耳机哪款合适",
        "我想买一件短袖",
        "查看详情: 凉感速干短袖 T 恤",
        "我要查订单什么时候发货",
        "这笔订单我要退货退款",
        "物流一直不更新怎么办",
        "怎么联系人工客服",
    ],
)
def test_real_ecommerce_tasks_reach_the_normal_agent_path(question: str):
    assert customer_scope_reply(question) is None


def test_catalog_references_and_confirmations_are_not_scope_blocked():
    assert customer_scope_reply("我刚才让你推荐的都是什么？") is None
    assert customer_scope_reply("刚才第二个有黑色吗？") is None
    assert customer_scope_reply("确认取消") is None
    assert customer_scope_reply("我想换小一码") is None


def test_unknown_product_after_shopping_clarification_stays_in_the_recommendation_flow():
    assert customer_scope_reply("风扇吧", previous_scope_question="夏天太热了，给我推荐一些商品") is None


def test_summary_after_scope_refusal_is_handled_without_opening_a_knowledge_answer():
    answer = customer_scope_reply(
        "汇总一下我们刚才都说什么了",
        previous_scope_question="自然语言处理的定义是啥",
        previous_scope_kinds=("out_of_scope",),
    )
    assert answer is not None
    assert "没有展开回答" in answer
    assert "自然语言处理（NLP）" not in answer


def test_order_context_product_question_is_allowed():
    assert customer_scope_reply("它是什么材质，适合学生吗", has_order_context=True) is None


def test_order_card_product_action_is_always_an_ecommerce_request():
    assert customer_scope_reply("查看商品") is None
    assert customer_scope_reply("查看商品", has_order_context=True) is None


@pytest.mark.parametrize(
    "question",
    ["雾蓝色有货吗", "这个颜色缺货吗", "什么时候补货", "XL 还有现货吗", "可以设置到货提醒吗"],
)
def test_inventory_followups_are_never_treated_as_general_knowledge(question: str):
    assert customer_scope_reply(question, has_catalog_context=True) is None


@pytest.mark.parametrize("question", ["不喜欢", "尺码不合适", "买错了", "未拆封不想要了", "撤销申请", "撤销退款"])
def test_short_after_sales_reasons_are_service_language(question: str):
    assert customer_scope_reply(question, has_order_context=True) is None


def test_refund_destination_change_is_blocked_before_planning():
    answer = customer_scope_reply("把退款打到别的银行卡")
    assert answer is not None
    assert "原支付路径" in answer


def test_correction_after_catalog_context_is_a_product_request():
    assert customer_scope_reply("我要的是充电器", has_catalog_context=True) is None


def test_explicit_purchase_of_an_unseen_product_stays_in_simulated_recommendation_flow():
    assert customer_scope_reply("我要一个电饭煲") is None
    assert customer_scope_reply("我要退款") is None
    assert not is_product_recommendation_request("我要退款")


def test_short_size_and_color_values_continue_catalog_flow():
    for value in ("M", "XL", "M码", "选L", "杏色", "黑色"):
        assert customer_scope_reply(value, has_catalog_context=True) is None
        assert is_product_recommendation_request(value, has_catalog_context=True)


def test_product_card_actions_bypass_planner_and_reach_catalog_executor():
    assert is_product_recommendation_request("查看详情：高腰 A 字半身裙", has_catalog_context=True)
    assert is_product_recommendation_request("选择规格：高腰 A 字半身裙", has_catalog_context=True)


def test_dynamic_catalog_option_allows_unseen_commerce_paraphrase_but_not_knowledge_question():
    answer = customer_scope_reply(
        "青柠绿后续还会再来一批吗",
        has_catalog_context=True,
        catalog_terms=("青柠绿", "轻量通勤外套"),
    )
    assert answer is None
    blocked = customer_scope_reply(
        "自然语言处理的定义是什么",
        has_catalog_context=True,
        catalog_terms=("青柠绿",),
    )
    assert blocked is not None


def test_package_interception_phrasings_reach_logistics_executor():
    questions = ["申请拦截", "帮我拦截这个包裹", "这个快递还能拦截吗", "运输中的订单申请拦截"]
    for question in questions:
        assert customer_scope_reply(question, has_order_context=True) is None
        assert classify_intent(question) == "logistics_issue"


def test_cancel_interception_is_distinct_from_cancelling_the_order():
    for question in ["取消拦截", "撤销拦截", "停止拦截", "不用拦截了"]:
        assert customer_scope_reply(question, has_order_context=True) is None
        assert classify_intent(question) == "cancel_interception"



@pytest.mark.parametrize(
    "question",
    [
        "取消仅退款",
        "撤销退货退款",
        "算了，不需要了，我自己留着吧",
        "我不想退了，留着吧",
    ],
)
def test_after_sales_cancellation_phrasings_share_one_intent(question: str):
    assert customer_scope_reply(question, has_order_context=True) is None
    assert wants_cancel_after_sales(question)
    assert classify_intent(question) == "cancel_after_sales"



def test_subjective_received_product_reasons_are_not_treated_as_refund_only_evidence():
    for question in ["不喜欢", "尺码不合适", "买错了", "改变主意不想要了"]:
        assert is_subjective_return_reason(question)


def test_partial_shipping_contact_is_parsed_and_only_missing_fields_are_requested():
    fields = _parse_shipping_contact("厦门大学翔安校区5号楼 wqr")
    assert fields["recipient"] == "wqr"
    assert fields["address"] == "厦门大学翔安校区5号楼"
    assert fields["phone"] == ""
    assert _missing_shipping_fields(fields) == ["联系电话"]


def test_complete_shipping_contact_supports_name_phone_address_order():
    fields = _parse_shipping_contact("wqr 13800138000 厦门大学翔安校区5号楼")
    assert fields == {
        "recipient": "wqr",
        "phone": "13800138000",
        "address": "厦门大学翔安校区5号楼",
    }
    assert _missing_shipping_fields(fields) == []



def test_incremental_shipping_contact_extracts_campus_address_phone_and_name():
    assert _parse_shipping_contact("厦大翔安校区 武倩茹") == {
        "recipient": "武倩茹", "phone": "", "address": "厦大翔安校区",
    }
    assert _parse_shipping_contact("13271250588 武倩茹") == {
        "recipient": "武倩茹", "phone": "13271250588", "address": "",
    }
    assert _parse_shipping_contact("武倩茹") == {
        "recipient": "武倩茹", "phone": "", "address": "",
    }


def test_unlabelled_campus_abbreviation_contact_is_parsed_as_one_complete_draft():
    assert _parse_shipping_contact("修改收货地址") == {
        "recipient": "", "phone": "", "address": "",
    }
    assert _parse_shipping_contact("我想修改地址") == {
        "recipient": "", "phone": "", "address": "",
    }
    assert _parse_shipping_contact("机器学习") == {
        "recipient": "", "phone": "", "address": "",
    }
    assert _parse_shipping_contact("福建厦门厦大翔安 武倩茹 13271250588") == {
        "recipient": "武倩茹",
        "phone": "13271250588",
        "address": "福建厦门厦大翔安",
    }
    assert _parse_shipping_contact("武倩茹 厦门大学") == {
        "recipient": "武倩茹",
        "phone": "",
        "address": "厦门大学",
    }
    assert _parse_shipping_contact("厦门大学") == {
        "recipient": "",
        "phone": "",
        "address": "厦门大学",
    }


def test_pending_address_plain_name_bypasses_scope_but_knowledge_does_not():
    assert customer_scope_reply(
        "武倩茹", has_order_context=True, pending_action="modify_address"
    ) is None
    assert customer_scope_reply(
        "武倩茹 厦门大学", has_order_context=True, pending_action="modify_address"
    ) is None
    assert customer_scope_reply(
        "福建厦门厦大翔安", has_order_context=True, pending_action="modify_address"
    ) is None
    assert customer_scope_reply(
        "机器学习", has_order_context=True, pending_action="modify_address"
    ) is not None
    assert customer_scope_reply(
        "卷积神经网络的定义", has_order_context=True, pending_action="modify_address"
    ) is not None


def test_submit_only_confirms_an_existing_service_flow():
    assert customer_scope_reply("提交", has_order_context=True, pending_action="logistics_issue") is None
    assert customer_scope_reply("提交", has_order_context=True) is not None
    assert _is_soft_confirm("提交") is True
    assert _is_soft_confirm("是") is True
    assert _is_soft_confirm("对") is True
    assert customer_scope_reply("查看拦截进度", has_order_context=True) is None
    assert customer_scope_reply("申请", has_order_context=True, pending_action="cancel_interception") is None
    assert customer_scope_reply("申请", has_order_context=True) is not None
    assert _is_soft_confirm("申请") is True


def test_short_ack_only_bypasses_scope_inside_pending_catalog_spec():
    assert customer_scope_reply("是的", has_catalog_context=True, has_pending_catalog_spec=True) is None
    assert customer_scope_reply("是的", has_catalog_context=True) is not None


def test_pending_address_input_bypasses_scope_without_opening_general_knowledge():
    assert customer_scope_reply(
        "厦门大学翔安校区5号楼 wqr",
        has_order_context=True,
        pending_action="modify_address",
    ) is None
    blocked = customer_scope_reply(
        "卷积神经网络的定义",
        has_order_context=True,
        pending_action="modify_address",
    )
    assert blocked is not None
