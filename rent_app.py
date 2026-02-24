import streamlit as st
import pandas as pd
from rapidfuzz import process, fuzz
import io
from collections import defaultdict

st.set_page_config(page_title="Studio Rent Tool", layout="wide")

MATCH_THRESHOLD = 85

st.title("Studio Rent Accounting Tool")
st.markdown("Upload bank CSV and tenant Excel file to generate rent ledger with payment dates and allocations.")

# ==========================
# FILE UPLOAD
# ==========================

bank_file = st.file_uploader("Upload bank CSV", type=["csv"])
tenant_file = st.file_uploader("Upload tenant Excel file", type=["xlsx"])

if bank_file and tenant_file:

    try:
        bank = pd.read_csv(bank_file)
        tenants = pd.read_excel(tenant_file)
    except Exception as e:
        st.error(f"File reading error: {e}")
        st.stop()

    required_bank_cols = {"Date", "Amount", "Name"}
    required_tenant_cols = {"Studio", "Artist Name", "Monthly Rent"}

    # Trim column names
    bank.columns = bank.columns.str.strip()
    tenants.columns = tenants.columns.str.strip()

    if not required_bank_cols.issubset(bank.columns):
        st.error("Bank CSV must contain columns: Date, Amount, Name")
        st.stop()

    if not required_tenant_cols.issubset(tenants.columns):
        st.error("Tenant file must contain columns: Studio, Artist Name, Monthly Rent")
        st.stop()

    # ==========================
    # CLEAN BANK DATA
    # ==========================

    bank["Date"] = pd.to_datetime(bank["Date"], errors="coerce")
    bank = bank.dropna(subset=["Date"])
    bank = bank.sort_values("Date")

    bank["Amount"] = pd.to_numeric(bank["Amount"], errors="coerce")
    bank = bank.dropna(subset=["Amount"])

    tenant_names = tenants["Artist Name"].tolist()

    def match_name(name):
        match, score, _ = process.extractOne(
            str(name),
            tenant_names,
            scorer=fuzz.token_sort_ratio
        )
        if score >= MATCH_THRESHOLD:
            return match
        return None

    bank["Matched Name"] = bank["Name"].apply(match_name)

    unmatched = bank[bank["Matched Name"].isna()]
    if len(unmatched) > 0:
        st.warning("Unmatched payments detected:")
        st.dataframe(unmatched[["Date", "Name", "Amount"]])

    bank = bank.dropna(subset=["Matched Name"])

    if bank.empty:
        st.error("No valid matched payments found.")
        st.stop()

    # ==========================
    # MONTH RANGE
    # ==========================

    bank["YearMonth"] = bank["Date"].dt.to_period("M")
    all_months = pd.period_range(
        start=bank["YearMonth"].min(),
        end=bank["YearMonth"].max(),
        freq="M"
    )

    # ==========================
    # BUILD LEDGER
    # ==========================

    records = []

    for _, tenant in tenants.iterrows():
        for month in all_months:
            records.append({
                "Studio": tenant["Studio"],
                "Artist Name": tenant["Artist Name"],
                "Month": month.to_timestamp(),  # we'll display as name later
                "Expected Rent": tenant["Monthly Rent"],
                "Allocated": 0.0,
                "Payment Details": []  # will hold tuples of (date, allocated, total_payment)
            })

    ledger = pd.DataFrame(records)
    ledger = ledger.sort_values(["Artist Name", "Month"])

    # ==========================
    # FIFO ALLOCATION WITH PAYMENT DATES & AMOUNTS
    # ==========================

    for tenant in tenant_names:

        tenant_payments = bank[bank["Matched Name"] == tenant].to_dict("records")
        tenant_ledger_idx = ledger[ledger["Artist Name"] == tenant].index

        for payment in tenant_payments:
            amount_remaining = payment["Amount"]
            payment_date = payment["Date"]

            for idx in tenant_ledger_idx:
                expected = ledger.at[idx, "Expected Rent"]
                allocated = ledger.at[idx, "Allocated"]
                still_due = expected - allocated

                if still_due > 0:
                    allocation = min(still_due, amount_remaining)
                    ledger.at[idx, "Allocated"] += allocation
                    amount_remaining -= allocation

                    # --- track payment detail ---
                    ledger.at[idx, "Payment Details"].append(
                        (payment_date, allocation, payment["Amount"])
                    )

                if amount_remaining <= 0:
                    break

    # ==========================
    # FORMAT PAYMENT DETAILS & SORT DATES
    # ==========================

    def format_payment_details(details):
        # sort by date
        details_sorted = sorted(details, key=lambda x: x[0])
        formatted = [f"{alloc:.0f}/{total:.0f} ({date.strftime('%Y-%m-%d')})" for date, alloc, total in details_sorted]
        return ", ".join(formatted) if formatted else ""

    ledger["Payment Dates"] = ledger["Payment Details"].apply(format_payment_details)
    ledger.drop(columns=["Payment Details"], inplace=True)

    # ==========================
    # FORMAT MONTH NAMES
    # ==========================

    ledger["Month"] = ledger["Month"].dt.strftime("%B")  # January, February, etc.

    # ==========================
    # STATUS & BALANCE
    # ==========================

    ledger["Difference"] = ledger["Allocated"] - ledger["Expected Rent"]

    def status(row):
        if row["Allocated"] == 0:
            return "Unpaid"
        elif row["Difference"] == 0:
            return "Paid"
        elif row["Difference"] < 0:
            return "Partially Paid"
        else:
            return "Overpaid"

    ledger["Status"] = ledger.apply(status, axis=1)
    ledger["Balance"] = ledger.groupby("Artist Name")["Difference"].cumsum()

    # ==========================
    # SUMMARY TABLE
    # ==========================

    summary = ledger.groupby("Artist Name").agg(
        Total_Expected=("Expected Rent", "sum"),
        Total_Paid=("Allocated", "sum"),
        Final_Balance=("Balance", "last")
    ).reset_index()

    # ==========================
    # DISPLAY
    # ==========================

    st.success("Report generated successfully.")

    tab1, tab2 = st.tabs(["Ledger", "Summary"])

    with tab1:
        st.dataframe(ledger)

    with tab2:
        st.write("Summary Table")
        st.dataframe(summary)

        st.write("Click to see payments per tenant:")
        for tenant in summary["Artist Name"]:
            # Filter ledger for this tenant
            tenant_ledger = ledger[ledger["Artist Name"] == tenant][[
                "Studio", "Month", "Expected Rent", "Allocated", "Status", "Payment Dates"
            ]]
            with st.expander(f"{tenant} — click to view payments"):
                st.dataframe(tenant_ledger)

    # ==========================
    # IN-MEMORY EXCEL EXPORT
    # ==========================

    
    buffer = io.BytesIO()

    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        ledger.to_excel(writer, sheet_name="Ledger", index=False)
        summary.to_excel(writer, sheet_name="Summary", index=False)

    buffer.seek(0)

    st.download_button(
        label="Download Excel Report",
        data=buffer,
        file_name="rent_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
