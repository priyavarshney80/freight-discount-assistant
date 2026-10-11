"""
Tier 2 evaluation: end-to-end golden dataset, run through the real system
including the local LLM (via LM Studio).

Unlike test_business_logic.py, this exercises the FULL pipeline: intent
detection via tool-calling, correct tool selection, argument extraction from
natural language, and the model's final phrasing (with the grounding judge
active as a safety net).

Each test case is checked with simple substring matching, since the model's
exact wording will vary. This is intentionally a looser check than the
business-logic tests — it is measuring "did the system behave correctly and
say something reasonably close to right", not "is the arithmetic exact"
(that's already covered by Tier 1).

Run this only when LM Studio is running with a model loaded.
"""

from llm_orchestrator import handle_query, reset_session

TEST_CASES = [
    {
        "id": "T1_single_seller_eligible",
        "query": "What is the discount for Myntra in August 2026?",
        "role": "seller",
        "expect_contains": ["426.99"],
    },
    {
        "id": "T2_single_seller_not_eligible",
        "query": "What is the discount for ABC Fashion in August 2026?",
        "role": "seller",
        "expect_contains_any": ["0", "not eligible", "no discount"],
    },
    {
        "id": "T3_policy_question",
        "query": "Does a returned order count as fulfilled?",
        "role": "seller",
        "expect_contains_any": ["no", "not", "does not"],
    },
    {
        "id": "T4_directory",
        "query": "How many sellers are there in total?",
        "role": "seller",
        "expect_contains": ["5"],
    },
    {
        "id": "T5_aggregate_as_admin",
        "query": "Show me top sellers by discount this quarter",
        "role": "admin",
        "expect_contains_any": ["myntra", "Myntra"],
    },
    {
        "id": "T6_aggregate_blocked_for_seller",
        "query": "Show me top sellers by discount this quarter",
        "role": "seller",
        "expect_contains_any": ["admin", "Admin", "restricted"],
    },
    {
        "id": "T7_what_if_simulator",
        "query": "If ABC Fashion fulfills 95 more orders in August 2026, will they be eligible?",
        "role": "seller",
        "expect_contains_any": ["yes", "Yes", "eligible"],
    },
    {
        "id": "T8_seller_comparison",
        "query": "Compare Myntra and ABC Fashion for August 2026",
        "role": "seller",
        "expect_contains": ["103", "6"],
    },
    {
        "id": "T9_unknown_seller",
        "query": "What is the discount for Flipkart?",
        "role": "seller",
        "expect_contains_any": ["not found", "no seller", "not on file", "could not find", "don't have"],
    },
    {
        "id": "T10_casual_chat",
        "query": "acha thik hai",
        "role": "seller",
        "expect_contains_any": ["help", "sure", "sounds good", "great", "let me know"],
    },
]


def run_eval():
    results = []

    for case in TEST_CASES:
        reset_session(case["id"])
        try:
            answer = handle_query(case["query"], user_role=case.get("role", "seller"), session_id=case["id"])
        except Exception as e:
            answer = f"ERROR: {e}"

        answer_lower = answer.lower()
        passed = True
        reasons = []

        for phrase in case.get("expect_contains", []):
            if phrase.lower() not in answer_lower:
                passed = False
                reasons.append(f"missing required phrase: '{phrase}'")

        any_list = case.get("expect_contains_any", [])
        if any_list and not any(p.lower() in answer_lower for p in any_list):
            passed = False
            reasons.append(f"none of expected phrases present: {any_list}")

        results.append({
            "id": case["id"],
            "query": case["query"],
            "answer": answer,
            "passed": passed,
            "reasons": reasons
        })

    total = len(results)
    passed_count = sum(1 for r in results if r["passed"])

    print("=" * 70)
    print(f"EVAL RESULTS: {passed_count}/{total} passed ({round(100 * passed_count / total, 1)}%)")
    print("=" * 70)
    print()

    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        print(f"[{status}] {r['id']}")
        print(f"        Query:  {r['query']}")
        print(f"        Answer: {r['answer']}")
        if not r["passed"]:
            print(f"        Reasons: {r['reasons']}")
        print()

    return results


if __name__ == "__main__":
    run_eval()