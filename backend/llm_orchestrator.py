import os
import re
import json
from openai import OpenAI
from business_rules import (
    get_seller_id,
    calculate_discount,
    calculate_total_discount_across_months,
    simulate_eligibility,
    get_order_status_breakdown,
    load_seller_master,
    ELIGIBILITY_THRESHOLD,
    DISCOUNT_PERCENTAGE
)
from analytics import get_top_sellers_by_discount, compare_sellers, compare_status_across_sellers
from rag_engine import retrieve_relevant_policy, get_seller_specific_document
from time_utils import resolve_query_months, get_latest_month

client = OpenAI(
    base_url=os.getenv("LLM_BASE_URL", "http://localhost:1234/v1"),
    api_key=os.getenv("LLM_API_KEY", "lm-studio")
)

MODEL_NAME = os.getenv("LLM_MODEL", "local-model")

# Session memory is now just the raw conversation history (like a normal chat),
# plus a small cache of any custom agreement terms we've already looked up.
# There is no keyword-based intent routing here anymore — the LLM decides,
# on every turn, whether it needs to call a tool or just reply naturally.
_sessions = {}

MAX_HISTORY_MESSAGES = 16

SYSTEM_PROMPT = (
    "You are Freight Ledger, a seller copilot for a B2B shipping platform. You help "
    "sellers and platform Admin/Ops users with questions about freight discount "
    "eligibility, order fulfillment, platform policy, and seller agreements.\n\n"
    "You have tools that fetch real data. These rules are mandatory:\n"
    "1. For ANY question about a specific seller's eligibility, discount, or order "
    "count, you MUST call get_seller_discount. Never answer this kind of question "
    "from memory or reasoning alone, even if you think you know the answer.\n"
    "2. For ANY question about platform rules, what counts as fulfilled, cancellations, "
    "returns, or 'what if' policy scenarios, you MUST call search_policy. Do not answer "
    "policy questions from your own general knowledge — always check the tool first.\n"
    "3. If the user does not mention a time period, do NOT ask them to clarify it first — "
    "just call the tool with period left out or set to 'latest'. You can always follow up "
    "afterward if the result suggests a different period would help.\n"
    "4. Never invent seller names, order counts, amounts, or policy terms yourself; only "
    "state what a tool actually returned.\n\n"
    "For greetings, small talk, acknowledgements, or vague messages with no factual "
    "question in them, do not call a tool — just respond naturally and briefly, and "
    "offer to help.\n\n"
    "If something is outside what your tools can answer, say so honestly instead of "
    "guessing — for example, say you don't have that information rather than making "
    "something up.\n\n"
    "Keep answers concise: 1-3 sentences for factual lookups, longer only if the user "
    "asks for a list or explanation."
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_seller_discount",
            "description": (
                "Look up a specific seller's fulfilled order count, discount eligibility, "
                "and discount amount for a time period. Use this for any question about "
                "one named seller's discount, eligibility, or fulfilled orders."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "seller_name": {
                        "type": "string",
                        "description": "The seller's name as the user referred to it"
                    },
                    "period": {
                        "type": "string",
                        "description": (
                            "The time period the user means, e.g. 'August 2026', "
                            "'last 3 months', 'this quarter', 'total', '2026'. "
                            "If the user did not mention a period, use 'latest'."
                        )
                    }
                },
                "required": ["seller_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_sellers",
            "description": (
                "Get a ranking of all sellers by total discount earned over a period. "
                "Restricted to Admin/Ops users."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "period": {
                        "type": "string",
                        "description": "Time period, e.g. 'this quarter', 'last 3 months', 'total'"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_policy",
            "description": (
                "Search the platform's general policy and, if a seller is named, their "
                "specific uploaded agreement, for rules about eligibility, order statuses, "
                "or other terms. Use for 'what counts as X', 'what if', 'does X count', "
                "or general rule questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The policy question to search for"},
                    "seller_name": {"type": "string", "description": "Seller name, if the question concerns their specific agreement"}
                },
                "required": ["question"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_sellers",
            "description": "Get the total count and names of all sellers registered on the platform.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "simulate_what_if",
            "description": (
                "Simulate whether a seller would become eligible for a discount if they "
                "fulfilled a certain number of additional orders this month. Use this for "
                "'what if I fulfill X more orders', 'how many more orders do I need to "
                "qualify', or similar hypothetical eligibility questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "seller_name": {"type": "string", "description": "The seller's name"},
                    "period": {
                        "type": "string",
                        "description": "The month to simulate, e.g. 'August 2026'. If not mentioned, use 'latest'."
                    },
                    "additional_orders": {
                        "type": "integer",
                        "description": "Number of hypothetical additional fulfilled orders. Use 0 if the user is only asking how many more orders they need, not proposing a specific number."
                    }
                },
                "required": ["seller_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "compare_sellers_tool",
            "description": (
                "Compare two or more named sellers' fulfilled orders, eligibility, and "
                "discount side by side for the same time period."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "seller_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Names of the sellers to compare (two or more)"
                    },
                    "period": {
                        "type": "string",
                        "description": "Time period, e.g. 'August 2026', 'this quarter'. If not mentioned, use 'latest'."
                    }
                },
                "required": ["seller_names"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_order_status_breakdown",
            "description": (
                "Get the count and percentage of a specific seller's orders by status "
                "(Fulfilled, Cancelled, Failed Delivery, Returned) for a period. Use for "
                "questions like 'how many cancelled orders does X have', 'what is Y's "
                "return rate', or any breakdown of order outcomes for one named seller."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "seller_name": {"type": "string", "description": "The seller's name"},
                    "period": {
                        "type": "string",
                        "description": "Time period, e.g. 'August 2026', 'last 3 months'. If not mentioned, use 'latest'."
                    }
                },
                "required": ["seller_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "compare_order_status",
            "description": (
                "Compare ONE order status (Cancelled, Failed Delivery, Returned, or "
                "Fulfilled) across ALL sellers on the platform for a period, ranked from "
                "highest to lowest rate. Use for questions like 'compare cancellation "
                "patterns among clients', 'which seller has the highest return rate', or "
                "any cross-seller pattern question about order outcomes. Restricted to "
                "Admin/Ops users, since it exposes other sellers' data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["Fulfilled", "Cancelled", "Failed Delivery", "Returned"],
                        "description": "Which order status to compare across sellers"
                    },
                    "period": {
                        "type": "string",
                        "description": "Time period, e.g. 'this quarter', 'last 3 months', 'total'. If not mentioned, use 'latest'."
                    }
                },
                "required": ["status"]
            }
        }
    }
]


def _extract_numbers(text):
    """
    Pulls out numeric tokens (handling commas and decimals) from a piece of
    text, e.g. 'Rs 5,199.64' -> '5199.64'.
    """
    matches = re.findall(r"[-+]?\d[\d,]*\.?\d*", text or "")
    return {m.replace(",", "") for m in matches}


def grounding_check(final_answer, tool_context):
    """
    Deterministic (non-LLM) safety check: every number the model states in its
    final answer must already appear somewhere in the tool's raw output. This
    catches the exact failure mode we saw earlier (a model quietly changing or
    inventing a number while paraphrasing). We use plain regex matching here on
    purpose instead of a second LLM call — it's free, instant, and cannot itself
    hallucinate.

    Single-digit numbers (0-9) are ignored, since these usually come from
    ordinary sentence construction ("in 2 months", "the 1st"), not from the
    figures we actually care about grounding.
    """
    if not tool_context:
        return True, set()

    answer_numbers = _extract_numbers(final_answer)
    context_numbers = _extract_numbers(tool_context)

    suspect_numbers = {n for n in answer_numbers if len(n.replace("-", "").replace(".", "")) >= 2}
    ungrounded = suspect_numbers - context_numbers
    return len(ungrounded) == 0, ungrounded


def _get_session(session_id):
    if session_id not in _sessions:
        _sessions[session_id] = {"messages": [], "agreement_cache": {}}
    return _sessions[session_id]


def reset_session(session_id):
    _sessions[session_id] = {"messages": [], "agreement_cache": {}}


def extract_seller_terms(seller_id, session):
    """
    Real-time RAG step: checks if this seller has a custom uploaded agreement,
    and if so, asks the LLM to extract the threshold and discount percentage
    from it. Falls back to standard policy if no custom agreement exists.
    Cached per session so we don't re-extract on every turn.
    """
    if seller_id in session["agreement_cache"]:
        return session["agreement_cache"][seller_id]

    default_threshold = ELIGIBILITY_THRESHOLD
    default_pct = DISCOUNT_PERCENTAGE * 100

    chunks = get_seller_specific_document(seller_id)
    if not chunks:
        result = (default_threshold, default_pct, False, None)
        session["agreement_cache"][seller_id] = result
        return result

    agreement_text = "\n".join(chunks)

    extraction_messages = [
        {"role": "system", "content": (
            "You extract structured numbers from a shipping seller's custom agreement. "
            "Read the agreement text and find two things: the minimum number of fulfilled "
            "orders required to be eligible for a freight discount (the threshold), and the "
            "discount percentage that applies. "
            "Respond with ONLY a JSON object, nothing else, in this exact format: "
            '{"threshold": <number or null>, "discount_percentage": <number or null>}. '
            "Use null for any value not clearly and explicitly stated in the text. "
            "Do not guess or infer a number that is not written."
        )},
        {"role": "user", "content": agreement_text}
    ]

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME, messages=extraction_messages, temperature=0.0
        )
        raw = response.choices[0].message.content.strip()
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        parsed = json.loads(json_match.group(0)) if json_match else {}
    except Exception:
        parsed = {}

    extracted_threshold = parsed.get("threshold")
    extracted_pct = parsed.get("discount_percentage")

    threshold = extracted_threshold if isinstance(extracted_threshold, (int, float)) else default_threshold
    pct = extracted_pct if isinstance(extracted_pct, (int, float)) else default_pct
    has_custom = (threshold != default_threshold) or (pct != default_pct)

    result = (threshold, pct, has_custom, agreement_text)
    session["agreement_cache"][seller_id] = result
    return result


def format_single_month_context(seller_name, result):
    eligible_text = "Yes" if result["eligible"] else "No"
    lines = [
        f"Seller: {seller_name}",
        f"Reference month: {result['eligibility_month']}",
        f"Fulfilled orders in that month: {result['fulfilled_orders']}",
        f"Orders needed to be eligible: {result['threshold_used']}",
        f"Eligible for discount: {eligible_text}",
        f"Discount percentage applied: {result['discount_percentage']}%",
    ]
    if result["freight_data_available"]:
        lines.append(f"Freight for {result['next_month']} (the month the discount applies to): Rs {result['original_freight']}")
        lines.append(f"Discount amount: Rs {result['discount_amount']}")
        lines.append(f"Final freight after discount: Rs {result['final_freight']}")
    else:
        lines.append(
            f"{result['next_month']} has not happened yet in our records, so the actual freight "
            f"amount for that month is not known yet. The discount rate above will apply once "
            f"{result['next_month']}'s freight is calculated, but no rupee amount can be given yet."
        )
    return "\n".join(lines)


def format_multi_month_context(seller_name, result):
    lines = [
        f"Seller: {seller_name}",
        f"Months considered: {', '.join(result['months_considered'])}",
        f"Total fulfilled orders across these months: {result['total_fulfilled_orders']}",
        f"Total discount earned across these months (where freight data was available): Rs {result['total_discount']}",
        "Month by month breakdown:"
    ]
    for m in result["month_breakdown"]:
        eligible_text = "Yes" if m["eligible"] else "No"
        if m["freight_data_available"]:
            lines.append(f"  - {m['month']}: {m['fulfilled_orders']} fulfilled orders, eligible: {eligible_text}, discount: Rs {m['discount_amount']}")
        else:
            lines.append(f"  - {m['month']}: {m['fulfilled_orders']} fulfilled orders, eligible: {eligible_text}, discount amount not yet known")
    return "\n".join(lines)


# ---------- Tool executors ----------
# Each one takes the LLM's arguments (already parsed from JSON), the session,
# and the user's role, and returns a plain-text result for the LLM to read.

def _exec_get_seller_discount(args, session, user_role):
    seller_name_in = args.get("seller_name", "")
    period = args.get("period") or "latest"

    seller_id, seller_name = get_seller_id(seller_name_in)
    if not seller_id:
        return f"No seller found matching '{seller_name_in}'. Tell the user this seller is not on file."

    months = resolve_query_months(period, fallback_months=None)
    threshold, pct, has_custom, _ = extract_seller_terms(seller_id, session)
    discount_fraction = pct / 100

    if len(months) > 1:
        result = calculate_total_discount_across_months(seller_id, months, threshold=threshold, discount_fraction=discount_fraction)
        context = format_multi_month_context(seller_name, result)
    else:
        month = months[0] if months else get_latest_month()
        result = calculate_discount(seller_id, month, threshold=threshold, discount_fraction=discount_fraction)
        context = format_single_month_context(seller_name, result)

    if has_custom:
        context = f"Note: {seller_name} has a custom agreement (threshold {threshold} fulfilled orders, discount {pct}%), which overrides standard policy.\n\n" + context
    else:
        context = f"Note: {seller_name} follows standard company policy (no custom agreement on file).\n\n" + context

    return context


def _exec_get_top_sellers(args, session, user_role):
    if user_role != "admin":
        return "ACCESS DENIED: This data is restricted to Admin/Ops users. Tell the user politely that cross-seller rankings require Admin access."

    period = args.get("period") or "total"
    months = resolve_query_months(period, fallback_months=None)
    top_sellers = get_top_sellers_by_discount(months)
    return f"Months considered: {', '.join(months)}\n" + top_sellers.to_string(index=False)


def _exec_search_policy(args, session, user_role):
    question = args.get("question", "")
    seller_name_in = args.get("seller_name")
    seller_id = None
    if seller_name_in:
        seller_id, _ = get_seller_id(seller_name_in)

    chunks = retrieve_relevant_policy(question, seller_id=seller_id)
    return "\n".join(chunks) if chunks else "No relevant policy text was found for this question."


def _exec_list_sellers(args, session, user_role):
    sellers_df = load_seller_master()
    names = sellers_df["Seller Name"].tolist()
    return f"Total sellers: {len(names)}\nNames: {', '.join(names)}"


def _exec_simulate_what_if(args, session, user_role):
    seller_name_in = args.get("seller_name", "")
    period = args.get("period") or "latest"
    additional_orders = args.get("additional_orders", 0)
    try:
        additional_orders = int(additional_orders)
    except (TypeError, ValueError):
        additional_orders = 0

    seller_id, seller_name = get_seller_id(seller_name_in)
    if not seller_id:
        return f"No seller found matching '{seller_name_in}'."

    months = resolve_query_months(period, fallback_months=None)
    month = months[0] if months else get_latest_month()

    threshold, pct, has_custom, _ = extract_seller_terms(seller_id, session)
    result = simulate_eligibility(seller_id, month, additional_orders, threshold=threshold)

    lines = [
        f"Seller: {seller_name}",
        f"Month: {month}",
        f"Current fulfilled orders: {result['current_fulfilled_orders']}",
        f"Threshold needed to be eligible: {result['threshold_used']}",
        f"Hypothetical additional fulfilled orders: {additional_orders}",
        f"Simulated total fulfilled orders: {result['simulated_fulfilled_orders']}",
        f"Would be eligible with this hypothetical: {'Yes' if result['would_be_eligible'] else 'No'}",
        f"Orders still needed from the CURRENT count to reach the threshold: {result['orders_still_needed']}",
    ]
    if result["average_freight_per_fulfilled_order"] is not None:
        lines.append(
            f"Average freight per fulfilled order this month: Rs {result['average_freight_per_fulfilled_order']} "
            f"(this is only a rough historical average, not a guaranteed figure — the actual discount "
            f"depends on next month's real freight)"
        )
    if has_custom:
        lines.insert(1, f"Note: {seller_name} has a custom agreement, threshold is {threshold} orders (not the standard 100).")
    return "\n".join(lines)


def _exec_compare_sellers(args, session, user_role):
    seller_names_in = args.get("seller_names", [])
    period = args.get("period") or "latest"

    if not seller_names_in or len(seller_names_in) < 2:
        return "Please name at least two sellers to compare."

    resolved = []
    unresolved = []
    for name in seller_names_in:
        sid, sname = get_seller_id(name)
        if sid:
            resolved.append((sid, sname))
        else:
            unresolved.append(name)

    if unresolved:
        return f"Could not find these sellers on file: {', '.join(unresolved)}. Please check the spelling."

    months = resolve_query_months(period, fallback_months=None)
    comparison = compare_sellers(resolved, months)

    lines = [f"Comparison for period: {', '.join(months)}"]
    for row in comparison:
        lines.append(
            f"- {row['seller_name']}: {row['fulfilled_orders']} fulfilled orders, "
            f"eligible: {'Yes' if row['eligible'] else 'No'}, discount: Rs {row['discount']}"
        )
    return "\n".join(lines)


def _exec_get_order_status_breakdown(args, session, user_role):
    seller_name_in = args.get("seller_name", "")
    period = args.get("period") or "latest"

    seller_id, seller_name = get_seller_id(seller_name_in)
    if not seller_id:
        return f"No seller found matching '{seller_name_in}'."

    months = resolve_query_months(period, fallback_months=None)

    totals = {"Fulfilled": 0, "Cancelled": 0, "Failed Delivery": 0, "Returned": 0}
    total_orders = 0
    for month in months:
        breakdown = get_order_status_breakdown(seller_id, month)
        for status in totals:
            totals[status] += breakdown[status]
        total_orders += breakdown["total_orders"]

    lines = [
        f"Seller: {seller_name}",
        f"Period: {', '.join(months)}",
        f"Total orders: {total_orders}"
    ]
    for status, count in totals.items():
        pct = round(100 * count / total_orders, 1) if total_orders > 0 else 0.0
        lines.append(f"{status}: {count} ({pct}%)")

    return "\n".join(lines)


def _exec_compare_order_status(args, session, user_role):
    if user_role != "admin":
        return "ACCESS DENIED: Cross-seller comparisons are restricted to Admin/Ops users. Tell the user politely that this needs Admin access."

    status = args.get("status", "Cancelled")
    period = args.get("period") or "latest"
    months = resolve_query_months(period, fallback_months=None)

    comparison = compare_status_across_sellers(status, months)

    lines = [f"{status} order comparison across all sellers, period: {', '.join(months)}"]
    for row in comparison:
        lines.append(
            f"- {row['seller_name']}: {row['status_count']} of {row['total_orders']} orders "
            f"were {status} ({row['rate_percent']}%)"
        )
    return "\n".join(lines)


TOOL_EXECUTORS = {
    "get_seller_discount": _exec_get_seller_discount,
    "get_top_sellers": _exec_get_top_sellers,
    "search_policy": _exec_search_policy,
    "list_sellers": _exec_list_sellers,
    "simulate_what_if": _exec_simulate_what_if,
    "compare_sellers_tool": _exec_compare_sellers,
    "get_order_status_breakdown": _exec_get_order_status_breakdown,
    "compare_order_status": _exec_compare_order_status,
}

INTENT_LABELS = {
    "get_seller_discount": "single_seller",
    "get_top_sellers": "aggregate",
    "search_policy": "policy",
    "list_sellers": "directory",
    "simulate_what_if": "simulation",
    "compare_sellers_tool": "comparison",
    "get_order_status_breakdown": "status_breakdown",
    "compare_order_status": "status_comparison",
}


def handle_query_with_meta(user_query, user_role="seller", session_id="default"):
    session = _get_session(session_id)
    session["messages"].append({"role": "user", "content": user_query})

    history = session["messages"][-MAX_HISTORY_MESSAGES:]
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.2
        )
    except Exception as e:
        print(f"LLM API error: {e}")
        answer = "Sorry, the AI service is temporarily unavailable. Please try again."

        session["messages"].append({"role": "assistant", "content": answer})
        return {"answer": answer, "intent": "error"}

    msg = response.choices[0].message
    intent_label = "chat"

    if msg.tool_calls:
        assistant_tool_msg = {
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ]
        }
        session["messages"].append(assistant_tool_msg)

        tool_contexts = []
        for tool_call in msg.tool_calls:
            fn_name = tool_call.function.name
            try:
                fn_args = json.loads(tool_call.function.arguments)
            except Exception:
                fn_args = {}

            executor = TOOL_EXECUTORS.get(fn_name)
            result_text = executor(fn_args, session, user_role) if executor else "Unknown tool."
            intent_label = INTENT_LABELS.get(fn_name, "chat")
            tool_contexts.append(result_text)

            session["messages"].append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result_text
            })

        followup_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + session["messages"][-MAX_HISTORY_MESSAGES:]
        final_response = client.chat.completions.create(
            model=MODEL_NAME, messages=followup_messages, temperature=0.2
        )
        final_answer = final_response.choices[0].message.content

        combined_context = "\n".join(tool_contexts)
        is_grounded, ungrounded_numbers = grounding_check(final_answer, combined_context)
        if not is_grounded:
            # The model's phrasing introduced a number that isn't in the actual
            # data. Rather than showing a possibly wrong answer, fall back to
            # the verified tool output directly.
            final_answer = (
                combined_context
                + "\n\n(Note: the assistant's original phrasing mentioned a figure not "
                + "present in the source data, so the verified data is shown above instead.)"
            )
    else:
        final_answer = msg.content

    session["messages"].append({"role": "assistant", "content": final_answer})
    session["messages"] = session["messages"][-30:]

    return {"answer": final_answer, "intent": intent_label}


def handle_query(user_query, user_role="seller", session_id="default"):
    return handle_query_with_meta(user_query, user_role, session_id)["answer"]


if __name__ == "__main__":
    print(handle_query("What is the eligible discount for ABC Fashion?"))
    print(handle_query("how did you calculate that?"))