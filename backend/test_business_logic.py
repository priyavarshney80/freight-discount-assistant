"""
Tier 1 evaluation: pure business logic tests.

These test the calculation engine directly (business_rules.py, analytics.py)
with no LLM involved at all. They run in under a second and should always
pass 100% of the time, since this layer is deterministic code, not AI. If
one of these fails, the bug is in the calculation logic itself, not in how
the LLM phrases anything.
"""

from business_rules import get_seller_id, calculate_discount, simulate_eligibility
from analytics import compare_sellers


def check(name, condition):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}")
    return condition


def run_logic_tests():
    results = []

    myntra_id, myntra_name = get_seller_id("Myntra")
    abc_id, abc_name = get_seller_id("ABC Fashion")

    r1 = calculate_discount(myntra_id, "August 2026")
    results.append(check("Myntra Aug 2026: 103 fulfilled orders", r1["fulfilled_orders"] == 103))
    results.append(check("Myntra Aug 2026: eligible = True", r1["eligible"] is True))
    results.append(check("Myntra Aug 2026: discount = Rs 426.99", r1["discount_amount"] == 426.99))

    r2 = calculate_discount(abc_id, "August 2026")
    results.append(check("ABC Fashion Aug 2026: not eligible", r2["eligible"] is False))
    results.append(check("ABC Fashion Aug 2026: discount = Rs 0", r2["discount_amount"] == 0.0))

    sim = simulate_eligibility(abc_id, "August 2026", 95)
    results.append(check("ABC Fashion +95 orders -> would be eligible", sim["would_be_eligible"] is True))
    results.append(check("ABC Fashion orders still needed = 94", sim["orders_still_needed"] == 94))

    comparison = compare_sellers([(myntra_id, myntra_name), (abc_id, abc_name)], ["August 2026"])
    results.append(check("Comparison returns exactly 2 sellers", len(comparison) == 2))
    results.append(check("Comparison: Myntra fulfilled = 103", comparison[0]["fulfilled_orders"] == 103))
    results.append(check("Comparison: ABC Fashion fulfilled = 6", comparison[1]["fulfilled_orders"] == 6))

    # A custom threshold/discount override should change the outcome
    custom_result = calculate_discount(abc_id, "August 2026", threshold=5, discount_fraction=0.15)
    results.append(check("Custom threshold=5 makes ABC Fashion eligible", custom_result["eligible"] is True))
    results.append(check("Custom discount_fraction=0.15 applied correctly", custom_result["discount_percentage"] == 15.0))

    passed = sum(results)
    total = len(results)
    print(f"\n{passed}/{total} business logic tests passed ({round(100 * passed / total, 1)}%)")
    return passed, total


if __name__ == "__main__":
    run_logic_tests()