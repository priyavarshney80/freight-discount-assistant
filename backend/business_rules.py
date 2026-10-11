import os
import pandas as pd
from openpyxl import load_workbook

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
ORDERS_FILE = os.path.join(DATA_DIR, "orders_data.xlsx")
SELLER_MASTER_FILE = os.path.join(DATA_DIR, "seller_master.xlsx")

ELIGIBILITY_THRESHOLD = 100
DISCOUNT_PERCENTAGE = 0.10


def load_orders_data():
    return pd.read_excel(ORDERS_FILE)


def load_seller_master():
    return pd.read_excel(SELLER_MASTER_FILE)


def get_seller_id(seller_name):
    sellers_df = load_seller_master()
    seller_name_clean = seller_name.strip().lower()

    for _, row in sellers_df.iterrows():
        if row["Seller Name"].strip().lower() == seller_name_clean:
            return row["Seller ID"], row["Seller Name"]

    for _, row in sellers_df.iterrows():
        if seller_name_clean in row["Seller Name"].strip().lower():
            return row["Seller ID"], row["Seller Name"]

    return None, None


def count_fulfilled_orders(seller_id, month):
    orders_df = load_orders_data()
    filtered = orders_df[
        (orders_df["Seller ID"] == seller_id) &
        (orders_df["Month"] == month) &
        (orders_df["Order Status"] == "Fulfilled")
    ]
    return len(filtered)


def get_total_freight_for_month(seller_id, month):
    """
    Sums the freight amount for a seller's FULFILLED orders only in a given
    month. Cancelled, Failed Delivery, and Returned orders are excluded, on
    the assumption that freight is not charged (or is reversed) when a
    shipment doesn't actually go through. Returns 0.0 if the seller had no
    fulfilled orders that month.
    """
    orders_df = load_orders_data()
    filtered = orders_df[
        (orders_df["Seller ID"] == seller_id) &
        (orders_df["Month"] == month) &
        (orders_df["Order Status"] == "Fulfilled")
    ]
    return round(filtered["Freight Amount (Rs)"].sum(), 2)


def _get_available_months():
    orders_df = load_orders_data()
    return set(orders_df["Month"].unique().tolist())


def get_next_month_label(month_str):
    dt = pd.to_datetime(month_str, format="%B %Y")
    next_dt = dt + pd.DateOffset(months=1)
    return next_dt.strftime("%B %Y")


def check_eligibility(seller_id, month, threshold=None):
    if threshold is None:
        threshold = ELIGIBILITY_THRESHOLD
    fulfilled_count = count_fulfilled_orders(seller_id, month)
    is_eligible = fulfilled_count >= threshold
    return {
        "seller_id": seller_id,
        "month": month,
        "fulfilled_orders": fulfilled_count,
        "eligible": is_eligible,
        "threshold_used": threshold
    }


def calculate_discount(seller_id, month, threshold=None, discount_fraction=None):
    """
    Eligibility is checked against `month`'s fulfilled orders. The discount
    then applies to freight for the FOLLOWING month. We use that following
    month's actual freight total if the data exists (i.e. that month has
    already happened in our records). If it hasn't happened yet, we cannot
    know the real freight number, so we report the eligibility and discount
    rate honestly without inventing a rupee amount.
    """
    if threshold is None:
        threshold = ELIGIBILITY_THRESHOLD
    if discount_fraction is None:
        discount_fraction = DISCOUNT_PERCENTAGE

    eligibility = check_eligibility(seller_id, month, threshold=threshold)
    next_month = get_next_month_label(month)
    freight_data_exists = next_month in _get_available_months()

    if freight_data_exists:
        original_freight = get_total_freight_for_month(seller_id, next_month)
        if eligibility["eligible"]:
            discount_amount = round(original_freight * discount_fraction, 2)
        else:
            discount_amount = 0.0
        final_freight = round(original_freight - discount_amount, 2)
    else:
        original_freight = None
        discount_amount = None
        final_freight = None

    return {
        "seller_id": seller_id,
        "eligibility_month": month,
        "next_month": next_month,
        "freight_data_available": freight_data_exists,
        "fulfilled_orders": eligibility["fulfilled_orders"],
        "eligible": eligibility["eligible"],
        "threshold_used": threshold,
        "original_freight": original_freight,
        "discount_percentage": round(discount_fraction * 100, 2) if eligibility["eligible"] else 0,
        "discount_amount": discount_amount,
        "final_freight": final_freight
    }


def calculate_total_discount_across_months(seller_id, months, threshold=None, discount_fraction=None):
    total_discount = 0.0
    total_fulfilled = 0
    month_breakdown = []

    for month in months:
        result = calculate_discount(seller_id, month, threshold=threshold, discount_fraction=discount_fraction)
        if result["discount_amount"] is not None:
            total_discount += result["discount_amount"]
        total_fulfilled += result["fulfilled_orders"]
        month_breakdown.append({
            "month": month,
            "fulfilled_orders": result["fulfilled_orders"],
            "eligible": result["eligible"],
            "discount_amount": result["discount_amount"],
            "freight_data_available": result["freight_data_available"]
        })

    return {
        "seller_id": seller_id,
        "months_considered": months,
        "total_fulfilled_orders": total_fulfilled,
        "total_discount": round(total_discount, 2),
        "month_breakdown": month_breakdown
    }


def simulate_eligibility(seller_id, month, additional_orders, threshold=None):
    """
    Answers 'what if I fulfilled N more orders this month' and 'how many more
    orders do I need to become eligible'. Also gives a rough discount estimate
    based on this month's average freight per fulfilled order — explicitly
    flagged as an estimate, not a guaranteed figure, since the actual discount
    depends on next month's real freight.
    """
    if threshold is None:
        threshold = ELIGIBILITY_THRESHOLD

    current_fulfilled = count_fulfilled_orders(seller_id, month)
    simulated_fulfilled = current_fulfilled + additional_orders
    would_be_eligible = simulated_fulfilled >= threshold
    orders_still_needed = max(0, threshold - current_fulfilled)

    orders_df = load_orders_data()
    fulfilled_this_month = orders_df[
        (orders_df["Seller ID"] == seller_id) &
        (orders_df["Month"] == month) &
        (orders_df["Order Status"] == "Fulfilled")
    ]
    avg_freight_per_order = None
    if len(fulfilled_this_month) > 0:
        avg_freight_per_order = round(fulfilled_this_month["Freight Amount (Rs)"].mean(), 2)

    return {
        "seller_id": seller_id,
        "month": month,
        "current_fulfilled_orders": current_fulfilled,
        "additional_orders_hypothetical": additional_orders,
        "simulated_fulfilled_orders": simulated_fulfilled,
        "threshold_used": threshold,
        "would_be_eligible": would_be_eligible,
        "orders_still_needed": orders_still_needed,
        "average_freight_per_fulfilled_order": avg_freight_per_order
    }


ORDER_STATUSES = ["Fulfilled", "Cancelled", "Failed Delivery", "Returned"]


def get_order_status_breakdown(seller_id, month):
    """
    Returns the count of orders in EACH status (not just Fulfilled) for a
    seller in a given month. This is the building block for cancellation
    rate, return rate, etc. questions.
    """
    orders_df = load_orders_data()
    filtered = orders_df[
        (orders_df["Seller ID"] == seller_id) &
        (orders_df["Month"] == month)
    ]
    total = len(filtered)
    counts = {status: int((filtered["Order Status"] == status).sum()) for status in ORDER_STATUSES}
    counts["total_orders"] = total
    counts["seller_id"] = seller_id
    counts["month"] = month
    return counts


def add_seller(seller_name):
    seller_name = seller_name.strip()
    sellers_df = load_seller_master()

    existing = sellers_df[sellers_df["Seller Name"].str.lower() == seller_name.lower()]
    if not existing.empty:
        return existing.iloc[0]["Seller ID"], existing.iloc[0]["Seller Name"], False

    existing_ids = sellers_df["Seller ID"].tolist()
    nums = [int(sid.replace("SLR", "")) for sid in existing_ids if str(sid).startswith("SLR")]
    next_num = max(nums) + 1 if nums else 1
    new_id = f"SLR{next_num:03d}"

    wb = load_workbook(SELLER_MASTER_FILE)
    ws = wb["Sellers"]
    ws.append([new_id, seller_name])
    wb.save(SELLER_MASTER_FILE)

    return new_id, seller_name, True


if __name__ == "__main__":
    seller_id, seller_name = get_seller_id("Myntra")
    print(f"Matched: {seller_name} ({seller_id})")
    result = calculate_discount(seller_id, "August 2026")
    print(result)