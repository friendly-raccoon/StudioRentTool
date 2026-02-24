import streamlit as st
import pandas as pd
from rapidfuzz import process, fuzz
import io

st.set_page_config(page_title="Studio Rent Tool", layout="wide")
MATCH_THRESHOLD = 85

st.title("Studio Rent Accounting Tool")
st.markdown(
    "Upload bank CSV and tenant Excel file (wide format, one row per tenant, columns per month) "
    "to generate rent ledger with payment dates and allocations.\n\n"
    "Tenant sheet should have 'Studio', 'Studio Order', 'Artist Name', and monthly rent columns.\n\n"
    "Bank CSV can optionally contain a 'Verwendungszweck' column."
)

# ==========================
# FILE UPLOAD
# ==========================
bank_file = st.file_uploader("Upload bank CSV", type=["csv"])
tenant_file = st.file_uploader("Upload tenant Excel file", type=["xlsx"])

if bank_file and tenant_file:
    try:
        bank = pd.read_csv(bank_file)
        tenants_wide = pd.read_excel(tenant_file)
    except Exception as e:
        st.error(f"File reading error: {e}")
        st.stop()

    # Trim column names
    bank.columns = bank.columns.str.strip()
    tenants_wide.columns = tenants_wide.columns.str.strip()

    # ==========================
    # CHECK COLUMNS
    # ==========================
    required_bank_cols = {"Date", "Amount", "Name"}
    required_tenant_base_cols = {"Studio", "Studio Order", "Artist Name"}

    if not required_bank_cols.issubset(bank.columns):
        st.error("Bank CSV must contain columns: Date, Amount, Name")
        st.stop()

    if not required_tenant_base_cols.issubset(tenants_wide.columns):
        st.error("Tenant sheet must contain columns: Studio, Studio Order, Artist Name, plus one column per month")
        st.stop()

    # Optional Verwendungszweck
    verwendungs_col = "Verwendungszweck" if "Verwendungszweck" in bank.columns else None

    # ==========================
    # SORT TENANTS BY STUDIO AND STUDIO ORDER
    # ==========================
    tenants_wide = tenants_wide.sort_values(["Studio", "Studio Order"])

    # ==========================
    # CLEAN BANK DATA
    # ==========================
    bank["Date"] = pd.to_datetime(bank["Date"], errors="coerce")
    bank = bank.dropna(subset=["Date"]).sort_values("Date")
    bank["Amount"] = pd.to_numeric(bank["Amount"], errors="coerce")
    bank = bank.dropna(subset=["Amount"])

    tenant_names = tenants_wide["Artist Name"].tolist()

    # ==========================
    # MATCH NAMES
    # ==========================
    def match_name(name):
        match, score, _ = process.extractOne(str(name), tenant_names, scorer=fuzz.token_sort_ratio)
        return match if score >= MATCH_THRESHOLD else None

    bank["Matched Name"] = bank["Name"].apply(match_name)
    unmatched = bank[bank["Matched Name"].isna()]

    if len(unmatched) > 0:
        st.warning("Unmatched payments detected in the CSV:")

    unmatched_display_cols = ["Date", "Name", "Amount"]
    if verwendungs_col:
        unmatched_display_cols.append(verwendungs_col)
    st.dataframe(unmatched[unmatched_display_cols])

    bank = bank.dropna(subset=["Matched Name"])
    if bank.empty:
        st.error("No valid matched payments found.")
        st.stop()

    # ==========================
    # CONVERT TENANT SHEET TO LONG FORMAT
    # ==========================
    month_cols = [c for c in tenants_wide.columns if c not in ["Studio", "Studio Order", "Artist Name"]]

    tenants_long = tenants_wide.melt(
        id_vars=["Studio", "Studio Order", "Artist Name"],
        value_vars=month_cols,
        var_name="Month",
        value_name="Expected Rent"
    )

    tenants_long['Month'] = pd.to_datetime(tenants_long['Month'], format="%b-%Y", errors='coerce')
    tenants_long = tenants_long.dropna(subset=["Expected Rent", "Month"])
    tenants_long["Expected Rent"] = pd.to_numeric(tenants_long["Expected Rent"], errors='coerce')

    # ==========================
    # BUILD LEDGER
    # ==========================
    ledger = tenants_long.copy()
    ledger["Allocated"] = 0.0
    ledger["Payment Details"] = []

    # ==========================
    # FIFO ALLOCATION WITH PAYMENT DATES & VERWENDUNGSZWECK
    # ==========================
    for tenant in tenant_names:
        tenant_payments = bank[bank["Matched Name"] == tenant].to_dict("records")
        tenant_ledger_idx = ledger[ledger["Artist Name"] == tenant].sort_values("Month").index

        for payment in tenant_payments:
            amount_remaining = payment["Amount"]
            payment_date = payment["Date"]
            beschreibung = payment[verwendungs_col] if verwendungs_col else ""

            for idx in tenant_ledger_idx:
                expected = ledger.at[idx, "Expected Rent"]
                allocated = ledger.at[idx, "Allocated"]
                still_due = expected - allocated

                if still_due > 0:
                    allocation = min(still_due, amount_remaining)
                    ledger.at[idx, "Allocated"] += allocation
                    amount_remaining -= allocation
                    ledger.at[idx, "Payment Details"].append(
                        (payment_date, allocation, payment["Amount"], beschreibung)
                    )
                if amount_remaining <= 0:
                    break

    # ==========================
    # FORMAT PAYMENT DETAILS & MONTH NAMES
    # ==========================
    def format_payment_details(details):
        details_sorted = sorted(details, key=lambda x: x[0])
        formatted = [
            f"{alloc:.0f}/{total:.0f} ({date.strftime('%Y-%m-%d')}" + 
            (f", {desc}" if desc else "") + ")"
            for date, alloc, total, desc in details_sorted
        ]
        return ", ".join(formatted) if formatted else ""

    ledger["Payment Dates"] = ledger["Payment Details"].apply(format_payment_details)
    ledger.drop(columns=["Payment Details"], inplace=True)
    ledger["Month"] = ledger["Month"].dt.strftime("%B")

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
        Studio=("Studio", "first"),
        Total_Expected=("Expected Rent", "sum"),
        Total_Paid=("Allocated", "sum"),
        Final_Balance=("Balance", "last")
    ).reset_index()

    # ==========================
    # TOGGLE FILTER FOR UNPAID/PARTIAL
    # ==========================
    show_only_due = st.checkbox("Show only Unpaid / Partially Paid months")

    if show_only_due:
        ledger_display = ledger[ledger["Status"].isin(["Unpaid", "Partially Paid"])]
    else:
        ledger_display = ledger.copy()

    # ==========================
    # DISPLAY IN TABS
    # ==========================
    st.success("Report generated successfully.")

    tab1, tab2, tab3 = st.tabs(["Ledger", "Summary", "Unmatched Payments"])

    with tab1:
        # Display ledger grouped by studio
        for studio, group in ledger_display.groupby("Studio"):
            st.subheader(f"Studio {studio}")
            st.dataframe(group)

    with tab2:
        st.dataframe(summary)

    with tab3:
        if not unmatched.empty:
            st.dataframe(unmatched[unmatched_display_cols])
        else:
            st.info("No unmatched payments.")

    # ==========================
    # EXCEL EXPORT (Ledger + Summary + Unmatched)
    # ==========================
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        ledger.to_excel(writer, sheet_name="Ledger", index=False)
        summary.to_excel(writer, sheet_name="Summary", index=False)
        unmatched.to_excel(writer, sheet_name="Unmatched Payments", index=False)

    buffer.seek(0)
    st.download_button(
        label="Download Excel Report",
        data=buffer,
        file_name="rent_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
