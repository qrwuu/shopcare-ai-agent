"""Versioned evaluation contract; assertions are deliberately model-agnostic."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

OrderRef = Literal["none", "paid", "shipped", "delivered", "completed"]


@dataclass(frozen=True)
class Turn:
    user: str
    expected_intents: tuple[str, ...] = ()
    require_clarification: bool = False
    answer_any: tuple[str, ...] = ()
    answer_forbidden: tuple[str, ...] = ()
    expected_effect: str = "none"
    expected_route: str | None = None
    max_llm_calls: int | None = None
    expected_tool: str | None = None
    expect_tool_success: bool | None = None
    require_confirmed_tool: bool = False


@dataclass(frozen=True)
class EvalCase:
    id: str
    category: str
    description: str
    order_ref: OrderRef = "none"
    turns: tuple[Turn, ...] = ()
    tags: tuple[str, ...] = ()
    expected_handoff: bool = False
    security_case: bool = False
    split: str = "test"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TurnResult:
    user: str
    answer: str
    latency_ms: float
    trace: dict[str, Any] = field(default_factory=dict)
    passed: bool = True
    failures: list[str] = field(default_factory=list)


@dataclass
class CaseResult:
    case: EvalCase
    turns: list[TurnResult]
    before: dict[str, Any]
    after: dict[str, Any]
    passed: bool
    failures: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "case": self.case.as_dict(),
            "turns": [asdict(turn) for turn in self.turns],
            "before": self.before,
            "after": self.after,
            "passed": self.passed,
            "failures": self.failures,
        }
