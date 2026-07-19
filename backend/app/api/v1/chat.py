"""Consumer chat API: one planning path, one trusted executor, one persisted transcript."""
import json

from typing import Optional

from fastapi import APIRouter, Depends, Header
from fastapi.responses import StreamingResponse

from app.api.v1.schemas import ChatRequest
from app.core.config import settings
from app.core.database import async_session_maker
from app.core.security import get_current_user_id
from app.services.agent_telemetry import capture_agent_telemetry, telemetry_summary
from app.services.conversation_agent import clarification_reply, grounded_fallback_reply, plan_customer_message
from app.services.customer_scope import customer_scope_reply, is_product_recommendation_request
from app.services.catalog_recommendation import catalog_context_terms, catalog_follow_up_answer, semantic_catalog_follow_up_answer
from app.services.conversation_service import add_message, ensure_title, get_or_create_session, remember_product_catalog

router = APIRouter()


@router.post("/chat")
async def chat(
    request: ChatRequest,
    current_user_id: int = Depends(get_current_user_id),
    x_eval_run_id: Optional[str] = Header(default=None),
):
    """Plan natural language first; only trusted code can execute state changes."""

    async def event_generator():
        client_thread_id = request.thread_id
        internal_thread_id = f"{current_user_id}_{client_thread_id}"
        question = request.question.strip()
        if not question:
            yield f"data: {json.dumps({'error': '请输入消息后再发送'}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
            return

        async with async_session_maker() as session:
            chat_session = await get_or_create_session(session, current_user_id, client_thread_id, request.order_sn)
            await ensure_title(session, chat_session, question)
            await add_message(session, current_user_id, client_thread_id, "user", question, order_sn=request.order_sn)
            await session.commit()

        order = None
        plan = None
        route = "unresolved"
        execution_error = False
        catalog_state_snapshot = None
        resolved_intent = ""
        catalog_data = (chat_session.meta_data or {}).get("last_catalog")
        catalog_context = bool(catalog_data)
        pending_catalog_spec = bool((chat_session.meta_data or {}).get("pending_presales_spec"))
        catalog_terms = catalog_context_terms(catalog_data)
        scope_pending_state = (chat_session.meta_data or {}).get("pending_action") or {}
        scope_pending_action = str(scope_pending_state.get("action") or "") if isinstance(scope_pending_state, dict) else ""
        if not scope_pending_action and isinstance((chat_session.meta_data or {}).get("pending_address_change"), dict):
            scope_pending_action = "modify_address"
        pending_action = scope_pending_action
        scope_state = (chat_session.meta_data or {}).get("scope_guard") or {}
        previous_scope_question = str(scope_state.get("question") or "")
        previous_scope_kinds = tuple(scope_state.get("recent_kinds") or ())
        shopping_request = is_product_recommendation_request(
            question,
            has_catalog_context=catalog_context,
            previous_scope_question=previous_scope_question,
        )
        async with capture_agent_telemetry() as telemetry:
            scoped_answer = customer_scope_reply(
                question,
                has_catalog_context=catalog_context,
                has_pending_catalog_spec=pending_catalog_spec,
                catalog_terms=catalog_terms,
                pending_action=scope_pending_action,
                has_order_context=bool(request.order_sn or chat_session.order_sn),
                previous_scope_question=previous_scope_question,
                previous_scope_kinds=previous_scope_kinds,
            )
            if scoped_answer:
                answer = scoped_answer
                if "银行卡" in question and any(term in question for term in ["退", "退款", "转到", "打到"]):
                    route = "safety_guard"
                    resolved_intent = "refund_only"
                else:
                    route = "scope_guard"
                    resolved_intent = "out_of_scope"
            else:
                try:
                    from app.services.agent_service import classify_intent, handle_consumer_message, hydrate_catalog_context

                    # Resolve named/ordinal card follow-ups before any recommender.
                    # Conversation-scoped demo cards are not part of the global seed,
                    # so a detail click must remain anchored to this session.
                    service_intent = classify_intent(question)
                    resolved_intent = service_intent
                    if scope_pending_action == "modify_address" and service_intent not in {"cancel_order", "cancel_after_sales", "return_refund", "refund_only", "exchange", "logistics", "logistics_issue", "human", "policy"}:
                        service_intent = "modify_address"
                        resolved_intent = "modify_address"
                    pending_state = (chat_session.meta_data or {}).get("pending_action") or {}
                    pending_action = str(pending_state.get("action") or "") if isinstance(pending_state, dict) else ""
                    trusted_service_intents = {
                        "policy",
                        "after_sales_intake", "return_refund", "refund_only", "exchange",
                        "damaged_or_missing", "cancel_after_sales", "after_sales_status",
                        "product", "product_detail", "price_negotiation",
                        "logistics", "logistics_issue", "urge_shipping",
                        "modify_address", "cancel_order", "cancel_interception",
                    }
                    has_bound_order = bool(request.order_sn or chat_session.order_sn)
                    if has_bound_order and service_intent in {"general", "presales", "product", "product_detail"} and (("不喜欢" in question and any(word in question for word in ["颜色", "尺码", "大小", "款式"])) or any(word in question for word in ["换成", "换个颜色", "换一码", "换小一码", "换大一码"])):
                        service_intent = "exchange"
                        resolved_intent = "exchange"
                    pending_service_flow = pending_action in {
                        "return_refund", "refund_only", "exchange", "damaged_or_missing", "cancel_after_sales",
                        "logistics_issue", "cancel_order", "cancel_interception", "modify_address",
                    }

                    catalog = (chat_session.meta_data or {}).get("last_catalog")
                    hydrate_catalog_context(catalog)
                    catalog_answer = catalog_follow_up_answer(catalog, question)
                    if service_intent != "policy" and not catalog_answer and not has_bound_order and not pending_catalog_spec and not shopping_request and isinstance(catalog, dict):
                        catalog_answer = await semantic_catalog_follow_up_answer(catalog, question)
                    if catalog_answer and isinstance(catalog, dict):
                        catalog_state_snapshot = dict(catalog)
                    if pending_catalog_spec and service_intent in {"general", "presales", "product", "product_detail"}:
                        resolved_intent = "product_recommendation"
                        answer = await handle_consumer_message(
                            question=question,
                            user_id=current_user_id,
                            thread_id=internal_thread_id,
                            order_sn=None,
                            intent_override="presales",
                        )
                        route = "trusted_executor"
                    elif service_intent == "policy":
                        resolved_intent = "policy"
                        answer = await handle_consumer_message(
                            question=question,
                            user_id=current_user_id,
                            thread_id=internal_thread_id,
                            order_sn=None,
                            intent_override="policy",
                        )
                        route = "trusted_executor"
                    elif catalog_answer:
                        resolved_intent = "product_question"
                        answer = catalog_answer
                        route = "trusted_executor"
                    elif service_intent in trusted_service_intents or pending_service_flow:
                        answer = await handle_consumer_message(
                            question=question,
                            user_id=current_user_id,
                            thread_id=internal_thread_id,
                            order_sn=request.order_sn,
                            intent_override=service_intent,
                            pending_action_override=pending_action,
                        )
                        route = "trusted_executor"
                    # Recommendation is a deterministic simulated-catalogue flow.
                    # Do not let a planner turn an explicit purchase request into
                    # a generic clarification or an unrelated knowledge answer.
                    elif shopping_request:
                        resolved_intent = "product_recommendation"
                        answer = await handle_consumer_message(
                            question=question,
                            user_id=current_user_id,
                            thread_id=internal_thread_id,
                            order_sn=request.order_sn,
                            intent_override="presales",
                        )
                        route = "trusted_executor"
                        if not answer:
                            answer = "我可以按品类、预算或使用场景继续帮你推荐商品。"
                    else:
                        plan, order, attachments, history = await plan_customer_message(
                            current_user_id, client_thread_id, question, request.order_sn
                        )
                        resolved_intent = plan.intent
                        if plan.needs_clarification:
                            answer = clarification_reply(plan)
                            route = "clarification"
                        else:
                            answer = await handle_consumer_message(
                                question=question,
                                user_id=current_user_id,
                                thread_id=internal_thread_id,
                                order_sn=order.order_sn if order else request.order_sn,
                                intent_override=plan.executor_intent,
                            )
                            route = "trusted_executor"
                            if not answer:
                                answer = await grounded_fallback_reply(plan, order, attachments, history, question)
                                route = "grounded_fallback"
                except Exception:
                    # Do not expose internal failures or silently drop the consumer's turn.
                    answer = "我已经收到你的问题，但这一步需要再核实一下。你可以补充订单号、商品名称或具体情况，我会继续处理。"
                    execution_error = True
                    route = "execution_error"

        async with async_session_maker() as session:
            chat_session = await get_or_create_session(session, current_user_id, client_thread_id, order.order_sn if order else request.order_sn)
            await add_message(session, current_user_id, client_thread_id, "assistant", answer, order_sn=order.order_sn if order else request.order_sn)
            meta_data = dict(chat_session.meta_data or {})
            if route == "scope_guard":
                previous_state = meta_data.get("scope_guard") or {}
                recent_kinds = list(previous_state.get("recent_kinds") or [])
                meta_data["scope_guard"] = {"question": question, "recent_kinds": (recent_kinds + ["out_of_scope"])[-4:]}
            else:
                meta_data.pop("scope_guard", None)
            if catalog_state_snapshot:
                meta_data["last_catalog"] = catalog_state_snapshot
            chat_session.meta_data = meta_data
            remember_product_catalog(chat_session, answer)
            await session.commit()

        canonical_intent = {"presales": "product_recommendation", "product": "product_question", "product_detail": "product_question", "logistics_issue": "logistics"}.get(resolved_intent, resolved_intent)
        yield f"data: {json.dumps({'token': answer}, ensure_ascii=False)}\n\n"
        if x_eval_run_id and settings.AGENT_EVAL_MODE and settings.EVAL_ISOLATED:
            trace = {
                "run_id": x_eval_run_id[:80],
                "plan": {"intent": plan.intent if plan else (canonical_intent or ("product_recommendation" if shopping_request and route == "trusted_executor" else "unknown")), "confidence": plan.confidence if plan else (1.0 if resolved_intent or (shopping_request and route == "trusted_executor") else 0), "needs_clarification": plan.needs_clarification if plan else False},
                "execution": {"route": route, "error": execution_error, "resolved_intent": canonical_intent or (plan.intent if plan else ""), "target_order_sn": order.order_sn if order else (request.order_sn or chat_session.order_sn or ""), "pending_action": pending_action},
                "telemetry": telemetry_summary(telemetry),
            }
            yield f"event: eval_trace\ndata: {json.dumps(trace, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
