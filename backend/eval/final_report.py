"""Generate a resume-safe release report from one final evaluation JSON artifact."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def _pct(value: object) -> str:
    return f"{value}%" if isinstance(value, (int, float)) else "—"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def make_markdown(payload: dict[str, Any]) -> str:
    metrics = payload["metrics"]
    results = payload["results"]
    failed = [row for row in results if not row["passed"]]
    categories: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in results:
        categories[row["case"]["category"]].append(row)

    failures = Counter()
    for row in failed:
        for reason in row.get("failures") or []:
            failures[reason] += 1

    blockers: list[str] = []
    if metrics.get("incorrect_execution_rate") not in (0, 0.0):
        blockers.append("检测到未确认关键操作或状态副作用")
    if metrics.get("scope_llm_bypass_rate") not in (0, 0.0):
        blockers.append("检测到范围门禁用例进入模型")
    security_failed = [row for row in failed if row["case"].get("security_case")]
    if security_failed:
        blockers.append(f"存在 {len(security_failed)} 条跨租户/安全用例失败")

    lines = [
        "# ShopCare Agent 最终离线评测报告", "",
        f"- 套件：`{payload.get('suite', 'unknown')}`",
        f"- 运行 ID：`{payload['run_id']}`",
        f"- 生成时间：`{payload['created_at']}`", "",
        "## 执行范围", "",
        f"- 固定用例：{metrics['cases']} 条；对话轮次：{metrics['turns']} 轮。",
        "- 真实 HTTP/SSE 链路，专用 PostgreSQL tmpfs + Redis 隔离环境；每例重置订单/售后状态并使用双用户验证数据隔离。",
        "- 覆盖商品推荐与详情、订单/物流、售后、关键操作确认、人工审核、模糊表达、跨用户隔离，以及非电商范围门禁。", "",
        "## 可验证指标", "",
        "| 指标 | 结果 |", "| --- | ---: |",
    ]
    for key, label in (
        ("task_completion_rate", "任务完成率"),
        ("intent_accuracy", "意图准确率"),
        ("auto_resolution_rate", "自动解决率"),
        ("handoff_recall", "应转人工召回率"),
        ("unnecessary_handoff_rate", "不必要转人工率"),
        ("critical_action_safety_rate", "关键操作安全率"),
        ("incorrect_execution_rate", "错误执行率"),
        ("scope_boundary_pass_rate", "范围门禁通过率"),
        ("scope_llm_bypass_rate", "范围门禁模型绕过率"),
        ("mean_latency_ms", "平均响应耗时 (ms)"),
        ("p95_latency_ms", "P95 响应耗时 (ms)"),
    ):
        lines.append(f"| {label} | {_pct(metrics.get(key)) if 'rate' in key or 'accuracy' in key else metrics.get(key, '—')} |")
    lines.extend(["", "## 分场景完成率", "", "| 场景 | 用例数 | 通过 | 完成率 |", "| --- | ---: | ---: | ---: |"])
    for category, rows in sorted(categories.items()):
        lines.append(f"| {category} | {len(rows)} | {sum(row['passed'] for row in rows)} | {_pct(round(sum(row['passed'] for row in rows) * 100 / len(rows), 2))} |")

    lines.extend(["", "## 发布判定", ""])
    if blockers:
        lines.extend(["当前不建议把该结果宣称为“全量发布通过”。阻断项："] + [f"- {item}" for item in blockers])
    else:
        lines.append("未发现范围门禁绕过、跨租户安全失败或未确认关键操作。其余失败项保留在下方，作为下一轮质量优化队列。")

    lines.extend(["", "## 失败案例与后续队列", ""])
    if not failed:
        lines.append("所有固定断言通过。")
    else:
        lines.append(f"- 确定性失败：{len(failed)} / {len(results)} 条。")
        for reason, count in failures.most_common(12):
            lines.append(f"- {count} 条：{reason}")
        lines.append("")
        for row in failed[:15]:
            answer = " / ".join((turn.get("answer") or "")[:180].replace("\n", " ") for turn in row.get("turns") or [])
            lines.append(f"- `{row['case']['id']}` · {row['case']['description']}：{'；'.join(row.get('failures') or [])}。回复：{answer}")

    lines.extend([
        "", "## 指标边界", "",
        "语义幻觉率、政策判断正确率、工具调用成功率，以及供应商未返回 usage 时的 Token/成本，均未伪造成数值；它们需要人工盲审、校准后的 Judge 或工具级 telemetry 后再纳入发布门禁。",
        "", "## 简历表述（仅使用本报告已验证的指标替换括号）", "",
        "搭建面向真实 HTTP/SSE 链路的 Agent 离线回归评测体系：固定 [用例数] 条中文用例覆盖商品推荐、订单/售后、关键操作确认、跨租户隔离与非电商范围门禁；在隔离环境执行并产出逐轮 trace、状态快照与人工复核队列，最终任务完成率 [任务完成率]、关键操作错误执行率 [错误执行率]、范围门禁模型绕过率 [范围门禁模型绕过率]。",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a resume-safe final evaluation report.")
    parser.add_argument("result")
    parser.add_argument("--output", default="eval/results/final-report.md")
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(make_markdown(_load(Path(args.result))), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
