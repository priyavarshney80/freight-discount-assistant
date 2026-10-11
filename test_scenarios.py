import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), "backend"))

from llm_orchestrator import handle_query

print("Test 1: Single seller query")
print(handle_query("What is the discount for Myntra?", user_role="seller"))

print("\nTest 2: Policy query")
print(handle_query("Does a returned order count as fulfilled?", user_role="seller"))

print("\nTest 3: Aggregate query as seller (should be blocked)")
print(handle_query("Show me top 10 sellers by discount", user_role="seller"))

print("\nTest 4: Aggregate query as admin")
print(handle_query("Show me top sellers by discount in the last 3 months", user_role="admin"))

print("\nTest 5: Multi-month total for a specific seller")
print(handle_query("What is the total discount Myntra has received so far?", user_role="seller"))
