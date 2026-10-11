import pandas as pd
from business_rules import load_seller_master, load_orders_data, calculate_discount, calculate_total_discount_across_months


def get_top_sellers_by_discount(months, top_n=10):
    sellers_df = load_seller_master()

    results = []
    for _, seller_row in sellers_df.iterrows():
        seller_id = seller_row["Seller ID"]
        seller_name = seller_row["Seller Name"]

        total_discount = 0.0
        total_fulfilled = 0
        eligible_in_any_month = False
        any_freight_data_missing = False

        for month in months:
            result = calculate_discount(seller_id, month)
            if result["discount_amount"] is not None:
                total_discount += result["discount_amount"]
            else:
                any_freight_data_missing = True
            total_fulfilled += result["fulfilled_orders"]
            if result["eligible"]:
                eligible_in_any_month = True

        results.append({
            "seller_id": seller_id,
            "seller_name": seller_name,
            "total_fulfilled_orders": total_fulfilled,
            "eligible_in_any_month": eligible_in_any_month,
            "total_discount": round(total_discount, 2),
            "note": "some months missing freight data" if any_freight_data_missing else ""
        })

    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values(by="total_discount", ascending=False)
    return results_df.head(top_n)


def compare_sellers(seller_id_name_pairs, months):
    """
    Takes a list of (seller_id, seller_name) tuples and a list of months, and
    returns each seller's fulfilled orders, eligibility, and discount for that
    period, side by side. Reuses the same calculation functions as a single
    seller lookup, so the numbers are guaranteed consistent with individual
    queries.
    """
    results = []
    for seller_id, seller_name in seller_id_name_pairs:
        if len(months) > 1:
            r = calculate_total_discount_across_months(seller_id, months)
            fulfilled = r["total_fulfilled_orders"]
            discount = r["total_discount"]
            eligible = any(m["eligible"] for m in r["month_breakdown"])
        else:
            r = calculate_discount(seller_id, months[0])
            fulfilled = r["fulfilled_orders"]
            discount = r["discount_amount"] if r["discount_amount"] is not None else 0.0
            eligible = r["eligible"]

        results.append({
            "seller_name": seller_name,
            "fulfilled_orders": fulfilled,
            "eligible": eligible,
            "discount": discount
        })
    return results


def compare_status_across_sellers(status, months):
    """
    For a given order status (Cancelled, Failed Delivery, Returned, or
    Fulfilled), returns every seller's count and rate for that status across
    the given months, sorted highest rate first. This is what powers
    'compare cancellation patterns among clients' type questions.
    """
    sellers_df = load_seller_master()
    orders_df = load_orders_data()

    results = []
    for _, seller_row in sellers_df.iterrows():
        seller_id = seller_row["Seller ID"]
        seller_name = seller_row["Seller Name"]

        filtered = orders_df[
            (orders_df["Seller ID"] == seller_id) &
            (orders_df["Month"].isin(months))
        ]
        total = len(filtered)
        status_count = int((filtered["Order Status"] == status).sum())
        rate_percent = round(100 * status_count / total, 1) if total > 0 else 0.0

        results.append({
            "seller_name": seller_name,
            "status_count": status_count,
            "total_orders": total,
            "rate_percent": rate_percent
        })

    results.sort(key=lambda r: r["rate_percent"], reverse=True)
    return results


if __name__ == "__main__":
    from time_utils import get_all_available_months
    print(get_top_sellers_by_discount(get_all_available_months()))