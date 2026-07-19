"""Create a compact before/after report from two evaluation result files."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

KEY_METRICS = (
    "task_completion_rate", "intent_accuracy", "auto_resolution_rate", "handoff_recall",
    "unnecessary_handoff_rate", "critical_action_safety_rate", "incorrect_execution_rate",
    "lexical_hallucination_rate", "scope_boundary_pass_rate", "scope_llm_bypass_rate", "mean_latency_ms", "p95_latency_ms",
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _delta(before: object, after: object) -> str:
    if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
        return "—"
    return f"{after - before:+.2f}"


def failure_rows(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["case"]["id"]: item for item in payload["results"] if not item["passed"]}


def make_markdown(before: dict[str, Any], after: dict[str, Any]) -> str:
    b_metrics, a_metrics = before["metrics"], after["metrics"]
    lines = [
        "# ShopCare Agent 离线评测 A/B 报告", "",
        f"- 基线：`{before['run_id']}`", f"- 优化后：`{after['run_id']}`", "",
        "## 核心指标", "", "| 指标 | 优化前 | 优化后 | 变化 |", "| --- | ---: | ---: | ---: |",
    ]
    for key in KEY_METRICS:
        lines.append(f"| {key} | {b_metrics.get(key, '—')} | {a_metrics.get(key, '—')} | {_delta(b_metrics.get(key), a_metrics.get(key))} |")
    lines.extend(["", "## 新增失败案例", ""])
    before_failures, after_failures = failure_rows(before), failure_rows(after)
    introduced = [key for key in after_failures if key not in before_failures]
    fixed = [key for key in before_failures if key not in after_failures]
    lines.append("- 已修复：" + ("、".join(fixed) if fixed else "无"))
    lines.append("- 新引入：" + ("、".join(introduced) if introduced else "无"))
    lines.extend(["", "## 结论边界", "", "本报告的意图、关键操作与状态副作用由确定性断言得出。语义幻觉、政策判断、工具调用成功率和 Token/成本必须在 `.review.jsonl` 完成人工或经校准的 LLM Judge 标注、以及补齐工具级 telemetry 后才可作为发布指标；本报告不会把缺失数据伪装为 0。", ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two ShopCare evaluation runs.")
    parser.add_argument("before")
    parser.add_argument("after")
    parser.add_argument("--output", default="eval/results/ab-report.md")
    args = parser.parse_args()
    content = make_markdown(_load(Path(args.before)), _load(Path(args.after)))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
