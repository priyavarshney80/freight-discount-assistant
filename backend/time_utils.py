import re
import pandas as pd
from business_rules import load_orders_data

MONTH_NAMES = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december"
]

WORD_TO_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}


def get_all_available_months():
    orders_df = load_orders_data()
    months = orders_df["Month"].unique().tolist()
    months_sorted = sorted(months, key=lambda m: pd.to_datetime(m, format="%B %Y"))
    return months_sorted


def get_latest_month():
    months = get_all_available_months()
    return months[-1] if months else None


def resolve_query_months(query, fallback_months=None):
    query_lower = query.lower()
    available_months = get_all_available_months()

    match = re.search(r"last (\d+|one|two|three|four|five|six) months?", query_lower)
    if match:
        n_str = match.group(1)
        n = int(n_str) if n_str.isdigit() else WORD_TO_NUM.get(n_str, 3)
        return available_months[-n:]

    if "quarter" in query_lower:
        return available_months[-3:]

    # Check a specific month name FIRST (more specific), before falling back
    # to a bare year match — otherwise "August 2026" would incorrectly match
    # the whole year instead of just August.
    for month_name in MONTH_NAMES:
        if month_name in query_lower:
            matched = [m for m in available_months if month_name in m.lower()]
            if matched:
                return matched

    year_match = re.search(r"\b(20\d{2})\b", query_lower)
    if year_match:
        year = year_match.group(1)
        year_months = [m for m in available_months if year in m]
        if year_months:
            return year_months

    if any(word in query_lower for word in ["total", "overall", "so far", "till now"]):
        return available_months

    # No explicit time reference in this message. If a previous turn in this
    # conversation already established a month/period, keep using that instead
    # of silently jumping to the latest month.
    if fallback_months:
        return fallback_months

    latest = get_latest_month()
    return [latest] if latest else []


if __name__ == "__main__":
    print(get_all_available_months())
    print(resolve_query_months("last 3 months"))
    print(resolve_query_months("total discount in 2026"))
    print(resolve_query_months("August"))
    print(resolve_query_months("what is the discount"))