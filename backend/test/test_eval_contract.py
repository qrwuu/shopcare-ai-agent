from eval.cases_v1 import load_cases
from eval.contracts import CaseResult, EvalCase, Turn, TurnResult
from eval.runner import build_metrics


def test_v1_suite_is_fixed_and_has_required_coverage():
    cases = load_cases()
    assert len(cases) == 80
    categories = {case.category for case in cases}
    assert {"product", "order", "critical_action", "after_sales", "ambiguity", "security"} <= categories
    assert any(case.security_case for case in cases)
    assert {"dev", "test", "security", "regression"} <= {case.split for case in cases}
    assert any(len(case.turns) > 1 for case in cases)


def test_metrics_do_not_invent_uninstrumented_values():
    case = EvalCase("case", "product", "example", turns=(Turn("hello", ("general",)),))
    result = CaseResult(case, [TurnResult("hello", "ok", 10, {"plan": {"intent": "general"}})], {}, {}, True)
    metrics = build_metrics([result])
    assert metrics["token_usage"] == "unavailable_from_model_provider"
    assert metrics["semantic_hallucination"].startswith("requires")


def test_final_suite_adds_scope_product_and_state_consistency_regressions():
    from eval.cases_final_v1 import load_cases as load_final_cases

    cases = load_final_cases()
    assert len(cases) == 96
    scope_cases = [case for case in cases if case.category == "scope"]
    assert len(scope_cases) == 8
    assert {case.id for case in cases} >= {"policy-01", "state-01", "state-02", "state-03", "state-04", "state-05", "state-06", "state-07"}
    guarded_turns = [turn for case in scope_cases for turn in case.turns if turn.expected_route == "scope_guard"]
    assert guarded_turns
    assert all(turn.max_llm_calls == 0 for turn in guarded_turns)
