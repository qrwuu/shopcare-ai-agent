# test/test_refund_tools.py
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.graph.tools import (
    check_refund_eligibility,
    submit_refund_application,
    query_refund_status
)


async def test_tools():
    """测试退货工具函数"""

    print("=" * 60)
    print("🧪 测试 LangGraph Tools")
    print("=" * 60)

    user_id = 1  # 假设用户ID为1

    # ========== 测试 1: 检查退货资格（不可退商品） ==========
    print("\n📋 测试 1: 检查退货资格 - 运动内衣（应被拒绝）")
    result = await check_refund_eligibility.ainvoke({
        "order_sn":  "SN20240001",
        "user_id": user_id
    })
    print(result)

    # ========== 测试 2: 检查退货资格（可退商品） ==========
    print("\n📋 测试 2: 检查退货资格 - 运动T恤（应该通过）")
    result = await check_refund_eligibility.ainvoke({
        "order_sn": "SN20240003",
        "user_id":  user_id
    })
    print(result)

    # ========== 测试 3: 提交退货申请 ==========
    print("\n📋 测试 3: 提交退货申请 - 篮球鞋")
    result = await submit_refund_application.ainvoke({
        "order_sn":  "SN20240004",
        "user_id":  user_id,
        "reason_detail": "鞋码偏大，穿着不舒服",
        "reason_category": "SIZE_NOT_FIT"
    })
    print(result)

    # ========== 测试 4: 查询所有退货申请 ==========
    print("\n📋 测试 4: 查询所有退货申请")
    result = await query_refund_status.ainvoke({
        "user_id": user_id
    })
    print(result)

    # ========== 测试 5: 查询指定申请 ==========
    print("\n📋 测试 5: 查询指定申请（申请编号 #1）")
    result = await query_refund_status.ainvoke({
        "user_id": user_id,
        "refund_id": 1
    })
    print(result)

    # ========== 测试 6: 跨用户访问（安全测试） ==========
    print("\n📋 测试 6: 跨用户访问 - 用户999查询用户1的订单")
    result = await check_refund_eligibility.ainvoke({
        "order_sn": "SN20240003",
        "user_id":  999  # 假冒的用户ID
    })
    print(result)

    print("\n" + "=" * 60)
    print("✅ 测试完成")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_tools())