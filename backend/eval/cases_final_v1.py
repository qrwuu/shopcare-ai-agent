"""Final fixed regression suite for the current ShopCare release.

It keeps the original 80 ecommerce, safety and tenant-isolation cases and adds
explicit service-boundary regressions discovered during product testing.
"""
from __future__ import annotations

from .cases_v1 import load_cases as load_v1_cases
from .contracts import EvalCase, Turn


def _scope_case(identifier: str, description: str, user: str, *, any_of: tuple[str, ...], forbidden: tuple[str, ...] = ()) -> EvalCase:
    return EvalCase(
        id=identifier,
        category="scope",
        description=description,
        turns=(
            Turn(
                user,
                answer_any=any_of,
                answer_forbidden=forbidden,
                expected_effect="no_mutation",
                expected_route="scope_guard",
                max_llm_calls=0,
            ),
        ),
        tags=("scope_boundary", "no_llm"),
        split="test",
    )


def load_cases() -> list[EvalCase]:
    cases = list(load_v1_cases())
    cases.extend(
        [
            _scope_case(
                "scope-01",
                "非电商知识：NLP 定义必须在模型前拦截",
                "自然语言处理的定义是啥",
                any_of=("店铺客服", "不在客服服务范围"),
                forbidden=("自然语言处理（NLP）",),
            ),
            _scope_case(
                "scope-02",
                "未见技术问题：卷积神经网络必须在模型前拦截",
                "卷积神经网络是怎么工作的",
                any_of=("店铺客服", "不在客服服务范围"),
                forbidden=("卷积层", "神经网络通常"),
            ),
            _scope_case(
                "scope-03",
                "非电商公司百科必须在模型前拦截",
                "抖音的公司是什么公司",
                any_of=("店铺客服", "不在客服服务范围"),
                forbidden=("字节跳动",),
            ),
            EvalCase(
                id="scope-04",
                category="scope",
                description="拒答后仍可回到正常短袖推荐与商品详情",
                turns=(
                    Turn(
                        "大模型的定义是什么",
                        answer_any=("店铺客服",),
                        expected_effect="no_mutation",
                        expected_route="scope_guard",
                        max_llm_calls=0,
                    ),
                    Turn(
                        "我想买一件夏天穿的短袖",
                        answer_any=("短袖", "PRODUCT_CARDS"),
                        expected_route="trusted_executor",
                    ),
                    Turn(
                        "查看详情: 凉感速干短袖 T 恤",
                        answer_any=("凉感速干短袖 T 恤", "价格"),
                        expected_route="trusted_executor",
                    ),
                ),
                tags=("scope_boundary", "context_recovery", "product"),
                split="regression",
            ),
            EvalCase(
                id="scope-05",
                category="scope",
                description="泛商品推荐不能被误判为非服务问题",
                turns=(
                    Turn(
                        "夏天太热了，给我推荐一些商品",
                        answer_any=("推荐", "PRODUCT_CARDS"),
                        expected_route="trusted_executor",
                    ),
                    Turn(
                        "我想买一个风扇",
                        answer_any=("推荐", "PRODUCT_CARDS", "商品"),
                        expected_route="trusted_executor",
                    ),
                ),
                tags=("scope_boundary", "generic_product", "context"),
                split="regression",
            ),
            _scope_case(
                "scope-06",
                "通用编程问题不能借商品上下文进入模型",
                "Python 怎么写一个爬虫",
                any_of=("店铺客服", "不在客服服务范围"),
                forbidden=("requests", "BeautifulSoup"),
            ),
            _scope_case(
                "scope-07",
                "金融百科问题不能借客服入口回答",
                "今天股票能买吗",
                any_of=("店铺客服", "不在客服服务范围"),
                forbidden=("投资", "股市"),
            ),
            _scope_case(
                "scope-08",
                "教育作业问题不能借客服入口回答",
                "帮我写一段机器学习论文摘要",
                any_of=("店铺客服", "不在客服服务范围"),
                forbidden=("摘要", "机器学习是一种"),
            ),
            EvalCase(
                id="policy-01",
                category="policy",
                description="无订单公开政策咨询覆盖定义、适用范围、流程、凭证、审核和价保",
                turns=(
                    Turn("七天无理由退款定义", answer_any=("七天无理由退货是指",), answer_forbidden=("选择订单", "不在客服服务范围"), expected_effect="no_mutation", expected_route="trusted_executor", max_llm_calls=0),
                    Turn("内衣拆封后能不能退", answer_any=("影响安全卫生", "通常不适用"), answer_forbidden=("选择订单", "不在客服服务范围"), expected_effect="no_mutation", expected_route="trusted_executor", max_llm_calls=0),
                    Turn("仅退款和退货退款有什么区别", answer_any=("不寄回商品", "需要按指引寄回"), answer_forbidden=("选择订单",), expected_effect="no_mutation", expected_route="trusted_executor", max_llm_calls=0),
                    Turn("发货以后还能取消吗", answer_any=("物流拦截", "不能直接"), answer_forbidden=("选择订单",), expected_effect="no_mutation", expected_route="trusted_executor", max_llm_calls=0),
                    Turn("少件需要上传哪些凭证", answer_any=("外包装照片", "快递面单"), answer_forbidden=("选择订单",), expected_effect="no_mutation", expected_route="trusted_executor", max_llm_calls=0),
                    Turn("什么情况会转人工审核", answer_any=("高金额", "证据不足"), answer_forbidden=("选择订单",), expected_effect="no_mutation", expected_route="trusted_executor", max_llm_calls=0),
                    Turn("价保差价怎么算", answer_any=("同一商品同一规格", "价保"), answer_forbidden=("选择订单",), expected_effect="no_mutation", expected_route="trusted_executor", max_llm_calls=0),
                ),
                tags=("policy", "no_order", "no_llm", "regression"),
                split="regression",
            ),
            EvalCase(
                id="state-01",
                category="after_sales",
                description="主观不喜欢从仅退款纠偏为退货退款，并可在原对话撤销同一售后记录",
                order_ref="delivered",
                turns=(
                    Turn("申请仅退款", answer_any=("仅退款",), expected_effect="no_mutation", expected_route="trusted_executor"),
                    Turn("不喜欢", answer_any=("退货退款", "不符合仅退款"), expected_effect="no_mutation", expected_route="trusted_executor"),
                    Turn("确认提交", answer_any=("退货退款申请", "申请编号"), expected_route="trusted_executor"),
                    Turn("取消仅退款", answer_any=("确认要撤销",), expected_effect="no_mutation", expected_route="trusted_executor"),
                    Turn(
                        "算了，不需要了，我自己留着吧",
                        answer_any=("已取消", "已经撤销"),
                        expected_effect="cancel_after_sales",
                        expected_route="trusted_executor",
                    ),
                ),
                tags=("state_consistency", "confirmation", "regression"),
                split="regression",
            ),
            EvalCase(
                id="state-02",
                category="product",
                description="会话绑定旧订单时，当前商品颜色与尺码短回复仍优先承接",
                order_ref="delivered",
                turns=(
                    Turn("给我推荐几款夏天穿的短袖", answer_any=("凉感速干短袖 T 恤", "PRODUCT_CARDS"), expected_effect="no_mutation", expected_route="trusted_executor", max_llm_calls=0),
                    Turn("选择规格：凉感速干短袖 T 恤", answer_any=("可选颜色", "可选尺码"), expected_effect="no_mutation", expected_route="trusted_executor", max_llm_calls=0),
                    Turn("浅灰有货吗", answer_any=("浅灰", "有货"), answer_forbidden=("不在客服服务范围",), expected_effect="no_mutation", expected_route="trusted_executor", max_llm_calls=0),
                    Turn("L", answer_any=("浅灰 / L", "库存状态"), answer_forbidden=("不在客服服务范围", "无法提供解释"), expected_effect="no_mutation", expected_route="trusted_executor", max_llm_calls=0),
                    Turn("浅灰什么时候补货", answer_any=("浅灰当前有货", "不需要等补货"), answer_forbidden=("¥899", "白色当前还有现货"), expected_effect="no_mutation", expected_route="trusted_executor", max_llm_calls=0),
                    Turn("什么时候补货", answer_any=("浅灰当前有货", "不需要等补货"), answer_forbidden=("¥899", "白色当前还有现货"), expected_effect="no_mutation", expected_route="trusted_executor", max_llm_calls=0),
                ),
                tags=("state_consistency", "catalog_context", "no_llm", "regression"),
                split="regression",
            ),
            EvalCase(
                id="state-03",
                category="critical_action",
                description="物流拦截接受简短提交确认并统一更新为拦截中",
                order_ref="shipped",
                turns=(
                    Turn("申请拦截", answer_any=("确认提交拦截申请",), expected_effect="no_mutation", expected_route="trusted_executor", max_llm_calls=0),
                    Turn("提交", answer_any=("拦截中", "拦截申请已提交"), answer_forbidden=("不在客服服务范围",), expected_effect="intercept_order", expected_route="trusted_executor", max_llm_calls=0),
                    Turn("查看拦截进度", answer_any=("正在处理中", "正在核实"), answer_forbidden=("不在客服服务范围",), expected_effect="no_mutation", expected_route="trusted_executor", max_llm_calls=0),
                ),
                tags=("state_consistency", "confirmation", "logistics_intercept", "no_llm", "regression"),
                split="regression",
            ),
            EvalCase(
                id="state-04",
                category="critical_action",
                description="修改地址支持手机号先行、下一轮姓名与校园简称合并，确认前不修改订单",
                order_ref="paid",
                turns=(
                    Turn("修改收货地址", answer_any=("当前地址", "收件人姓名"), expected_effect="no_mutation", expected_route="trusted_executor", max_llm_calls=0),
                    Turn("13271250588", answer_any=("电话：13271250588", "还缺收件人姓名、详细地址"), answer_forbidden=("收件人：修改收货地址",), expected_effect="no_mutation", expected_route="trusted_executor", max_llm_calls=0),
                    Turn("武倩茹 厦门大学", answer_any=("新收货信息", "确认修改"), answer_forbidden=("还缺", "不在客服服务范围"), expected_effect="no_mutation", expected_route="trusted_executor", max_llm_calls=0),
                ),
                tags=("state_consistency", "modify_address", "multi_turn_memory", "no_llm", "regression"),
                split="regression",
            ),
            EvalCase(
                id="state-05",
                category="critical_action",
                description="已发货改地址失败后，明确物流拦截诉求必须覆盖旧地址流程",
                order_ref="shipped",
                turns=(
                    Turn("修改收货地址", answer_any=("不能直接修改地址",), expected_effect="no_mutation", expected_route="trusted_executor", max_llm_calls=0),
                    Turn("帮我拦截这个订单", answer_any=("确认提交拦截申请",), answer_forbidden=("不能直接修改地址", "联系物流修改"), expected_effect="no_mutation", expected_route="trusted_executor", max_llm_calls=0),
                ),
                tags=("state_consistency", "intent_switch", "logistics_intercept", "no_llm", "regression"),
                split="regression",
            ),
            EvalCase(
                id="state-06",
                category="critical_action",
                description="物流拦截确认问句支持单字‘是’并真实更新订单状态",
                order_ref="shipped",
                turns=(
                    Turn("申请拦截", answer_any=("确认提交拦截申请",), expected_effect="no_mutation", expected_route="trusted_executor", max_llm_calls=0),
                    Turn("是", answer_any=("拦截中", "拦截申请已提交"), answer_forbidden=("不在客服服务范围", "已经发出了，平台现在不能直接修改地址"), expected_effect="intercept_order", expected_route="trusted_executor", max_llm_calls=0),
                ),
                tags=("state_consistency", "confirmation", "logistics_intercept", "no_llm", "regression"),
                split="regression",
            ),
            EvalCase(
                id="state-07",
                category="critical_action",
                description="撤销物流拦截不误判为取消订单，单词‘申请’可确认人工核实",
                order_ref="shipped",
                turns=(
                    Turn("申请拦截", answer_any=("确认提交拦截申请",), expected_effect="no_mutation", expected_route="trusted_executor", max_llm_calls=0),
                    Turn("是", answer_any=("拦截中",), expected_effect="intercept_order", expected_route="trusted_executor", max_llm_calls=0),
                    Turn("取消拦截", answer_any=("确认申请撤销物流拦截",), answer_forbidden=("平台不能直接取消", "是否还能拦截物流"), expected_effect="no_mutation", expected_route="trusted_executor", max_llm_calls=0),
                    Turn("申请", answer_any=("撤销物流拦截申请已提交", "人工核实中"), answer_forbidden=("不在客服服务范围", "取消订单"), expected_effect="no_mutation", expected_route="trusted_executor", max_llm_calls=0),
                ),
                tags=("state_consistency", "confirmation", "cancel_interception", "handoff", "no_llm", "regression"),
                expected_handoff=True,
                split="regression",
            ),
        ]
    )
    assert len(cases) == 96, f"final-v1 suite must stay fixed at 96 cases, got {len(cases)}"
    return cases
