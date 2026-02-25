import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from thefuzz import process
from io import BytesIO

st.set_page_config(page_title="Studio Rent Allocation Pro", layout="wide")
st.title("🏠 Studio Rent Allocation PRO")

st.markdown("""
Advanced Features:
- Smart fuzzy matching (Name + Verwendungszweck)
- Automatic month detection
- Multi-year support
- Payment transaction log
- Manual correction option
- Visual dashboard
- Excel export (3 sheets)
""")

# ---------------------------------------------------
# 1️⃣ TENANT UPLOAD
# ---------------------------------------------------

tenant_file = st.file_uploader("Upload Tenant Excel", type=["xlsx","xls"])

if tenant_file:
    tenants_raw = pd.read_excel(tenant_file)

    st.write("Detected columns:", list(tenants_raw.columns))

    studio_col = st.selectbox("Studio column", tenants_raw.columns)
    artist_col = st.selectbox("Artist column", tenants_raw.columns)

    tenants = tenants_raw.copy()
    tenants["Studio"] = tenants[studio_col].astype(str).str.strip()
    tenants["Artist"] = tenants[artist_col].astype(str).str.strip()

    # Detect numeric columns automatically as rent columns
    numeric_cols = tenants.select_dtypes(include="number").columns.tolist()
    month_cols = numeric_cols

    # Initialize tracking
    for m in month_cols:
        tenants[f"{m}_Paid"] = 0.0
        tenants[f"{m}_Balance"] = tenants[m]

    st.subheader("Tenants")
    st.dataframe(tenants)

# ---------------------------------------------------
# 2️⃣ PAYMENTS UPLOAD
# ---------------------------------------------------

payment_file = st.file_uploader("Upload Payments CSV", type="csv")

if payment_file:
    payments_raw = pd.read_csv(payment_file)

    st.write("Detected columns:", list(payments_raw.columns))

    payer_col = st.selectbox("Payer column", payments_raw.columns)
    amount_col = st.selectbox("Amount column", payments_raw.columns)
    date_col = st.selectbox("Payment date column", payments_raw.columns)
    desc_col = st.selectbox("Verwendungszweck (Description) column", payments_raw.columns)

    payments = payments_raw[[payer_col, amount_col, date_col, desc_col]].copy()
    payments.columns = ["Payer","Amount Paid","Payment Date","Description"]

    payments["Payer"] = payments["Payer"].astype(str).str.strip()
    payments["Description"] = payments["Description"].astype(str).str.strip()

    payments["Amount Paid"] = (
        payments["Amount Paid"]
        .astype(str)
        .str.replace(",", ".", regex=False)
    )

    payments["Amount Paid"] = pd.to_numeric(payments["Amount Paid"], errors="coerce")
    payments = payments[payments["Amount Paid"].notna()]
    payments = payments[payments["Amount Paid"] > 0]

    payments["Payment Date"] = pd.to_datetime(payments["Payment Date"], errors="coerce")
    payments = payments.sort_values("Payment Date")

    st.subheader("Filtered Incoming Payments")
    st.dataframe(payments)

# ---------------------------------------------------
# 3️⃣ ALLOCATION ENGINE
# ---------------------------------------------------

if tenant_file and payment_file:

    tenants_copy = tenants.copy()
    unmatched = []
    transaction_log = []

    threshold = 75

    match_choices = (
        tenants_copy["Artist"] + " | Studio " + tenants_copy["Studio"]
    ).tolist()

    for i, pay_row in payments.iterrows():

        combined_text = pay_row["Payer"] + " " + pay_row["Description"]

        match = process.extractOne(combined_text, match_choices)

        if match:
            best_match, score = match
            artist_name = best_match.split(" | ")[0]

            if score < threshold:
                # Manual override UI
                artist_name = st.selectbox(
                    f"Low match score ({score}) for '{combined_text}' → Select correct tenant:",
                    tenants_copy["Artist"].tolist(),
                    key=f"manual_{i}"
                )

            idx = tenants_copy[tenants_copy["Artist"] == artist_name].index[0]
            remaining = pay_row["Amount Paid"]

            for m in month_cols:
                month_balance = tenants_copy.at[idx, f"{m}_Balance"]

                if month_balance <= 0:
                    continue

                if remaining >= month_balance:
                    tenants_copy.at[idx, f"{m}_Paid"] += month_balance
                    tenants_copy.at[idx, f"{m}_Balance"] = 0
                    remaining -= month_balance
                else:
                    tenants_copy.at[idx, f"{m}_Paid"] += remaining
                    tenants_copy.at[idx, f"{m}_Balance"] -= remaining
                    remaining = 0
                    break

            transaction_log.append({
                "Payment Date": pay_row["Payment Date"],
                "Payer": pay_row["Payer"],
                "Description": pay_row["Description"],
                "Amount": pay_row["Amount Paid"],
                "Matched Artist": artist_name,
                "Match Score": score,
                "Remaining Credit": remaining
            })

        else:
            unmatched.append(pay_row.to_dict())

    # ---------------------------------------------------
    # 4️⃣ SUMMARY
    # ---------------------------------------------------

    paid_cols = [f"{m}_Paid" for m in month_cols]
    balance_cols = [f"{m}_Balance" for m in month_cols]

    tenants_copy["Total Expected"] = tenants_copy[month_cols].sum(axis=1)
    tenants_copy["Total Paid"] = tenants_copy[paid_cols].sum(axis=1)
    tenants_copy["Remaining Balance"] = tenants_copy[balance_cols].sum(axis=1)

    st.subheader("📊 Allocation Summary")
    st.dataframe(tenants_copy)

    # ---------------------------------------------------
    # 5️⃣ DASHBOARD
    # ---------------------------------------------------

    st.subheader("📈 Expected vs Paid")

    fig, ax = plt.subplots()
    ax.bar(tenants_copy["Artist"], tenants_copy["Total Expected"], alpha=0.6)
    ax.bar(tenants_copy["Artist"], tenants_copy["Total Paid"], alpha=0.6)
    ax.set_xticklabels(tenants_copy["Artist"], rotation=45)
    st.pyplot(fig)

    # ---------------------------------------------------
    # 6️⃣ EXPORT
    # ---------------------------------------------------

    unmatched_df = pd.DataFrame(unmatched)
    log_df = pd.DataFrame(transaction_log)

    def to_excel(summary, unmatched, log):
        output = BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            summary.to_excel(writer, sheet_name="Summary", index=False)
            unmatched.to_excel(writer, sheet_name="Unmatched", index=False)
            log.to_excel(writer, sheet_name="Transaction Log", index=False)
        return output.getvalue()

    excel_data = to_excel(tenants_copy, unmatched_df, log_df)

    st.download_button(
        "📥 Download Full Excel Report",
        excel_data,
        file_name="studio_rent_allocation_pro.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
