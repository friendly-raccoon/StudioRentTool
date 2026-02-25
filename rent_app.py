import streamlit as st
import pandas as pd
from thefuzz import process
from io import BytesIO

st.set_page_config(page_title="Monthly Rent Allocation", layout="wide")
st.title("🏠 Monthly Rent Allocation App")

st.markdown("""
Upload your **tenant Excel** with expected rent per month and **bank payment CSV**. 
The app allocates payments month by month, tracks balances, and generates an Excel report.
""")

# --- Upload Tenant Excel ---
tenant_file = st.file_uploader("Upload Tenant Excel", type=["xlsx","xls"])
if tenant_file:
    xls = pd.ExcelFile(tenant_file)
    sheet_name = st.selectbox("Select sheet with tenant data", xls.sheet_names)
    tenants = pd.read_excel(xls, sheet_name=sheet_name)
    
    st.write("Columns detected:", list(tenants.columns))
    
    studio_col = st.selectbox("Studio column", tenants.columns)
    artist_col = st.selectbox("Artist column", tenants.columns)
    
    month_cols = st.multiselect("Select columns for expected rent per month", tenants.columns)
    tenants = tenants[[studio_col, artist_col] + month_cols]
    tenants.columns = ["Studio","Artist"] + month_cols
    
    # Initialize balance columns
    for month in month_cols:
        tenants[f"{month}_Paid"] = 0.0
        tenants[f"{month}_Balance"] = tenants[month]
    
    st.subheader("Tenant List with Monthly Expected Rent")
    st.dataframe(tenants)

# --- Upload Payment CSV ---
payment_file = st.file_uploader("Upload Payments CSV", type="csv")
if payment_file:
    payments = pd.read_csv(payment_file)
    st.write("Columns detected:", list(payments.columns))
    
    payer_col = st.selectbox("Payer column", payments.columns)
    amount_col = st.selectbox("Amount Paid column", payments.columns)
    date_col = st.selectbox("Payment Date column", payments.columns)
    
    payments = payments[[payer_col, amount_col, date_col]]
    payments.columns = ["Payer","Amount Paid","Payment Date"]
    payments["Amount Paid"] = payments["Amount Paid"].astype(float)
    payments = payments[payments["Amount Paid"] > 0]  # incoming payments
    
    st.subheader("Payments")
    st.dataframe(payments)

# --- Allocate Payments Monthly ---
if tenant_file and payment_file:
    tenants_copy = tenants.copy()
    unmatched_rows = []

    # Fuzzy matching threshold
    threshold = 80
    
    # Sort payments by date
    payments = payments.sort_values("Payment Date")
    
    for _, pay_row in payments.iterrows():
        payer_name = str(pay_row["Payer"]).strip()
        amount = float(pay_row["Amount Paid"])
        
        # Fuzzy match artist
        artist_list = tenants_copy["Artist"].dropna().astype(str).tolist()
        best_match, score = process.extractOne(str(payer_name), artist_list)
        
        if score >= threshold:
            idx = tenants_copy[tenants_copy["Artist"] == best_match].index[0]
            
            # Allocate payment month by month
            remaining = amount
            for month in month_cols:
                month_balance = tenants_copy.at[idx,f"{month}_Balance"]
                if month_balance <= 0:
                    continue
                if remaining >= month_balance:
                    tenants_copy.at[idx,f"{month}_Paid"] += month_balance
                    tenants_copy.at[idx,f"{month}_Balance"] = 0
                    remaining -= month_balance
                else:
                    tenants_copy.at[idx,f"{month}_Paid"] += remaining
                    tenants_copy.at[idx,f"{month}_Balance"] -= remaining
                    remaining = 0
                    break
            # Any leftover remaining? could be carried as overpayment (optional)
        else:
            unmatched_rows.append({"Payer":payer_name,"Amount Paid":amount,"Payment Date":pay_row["Payment Date"]})
    
    st.subheader("Allocated Payments")
    st.dataframe(tenants_copy)
    
    # Unmatched payments
    unmatched_df = pd.DataFrame(unmatched_rows)
    if not unmatched_df.empty:
        st.subheader("⚠️ Unmatched Payments")
        st.dataframe(unmatched_df)
    
    # --- Export Excel ---
    def to_excel(allocated, unmatched):
        output = BytesIO()
        writer = pd.ExcelWriter(output, engine="xlsxwriter")
        allocated.to_excel(writer, index=False, sheet_name="Allocated Payments")
        unmatched.to_excel(writer, index=False, sheet_name="Unmatched Payments")
        writer.save()
        return output.getvalue()
    
    excel_data = to_excel(tenants_copy, unmatched_df)
    st.download_button(
        label="📥 Download Excel with Monthly Allocations",
        data=excel_data,
        file_name="monthly_rent_allocation.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
