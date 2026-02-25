import streamlit as st
import pandas as pd
from thefuzz import process
from io import BytesIO

st.set_page_config(page_title="Advanced Rent Allocation", layout="wide")
st.title("🏠 Advanced Rent Allocation App")

st.markdown("""
Upload your **tenant Excel** and **bank payment CSV**. The app will allocate payments, compute partial/overpayments, maintain balances, 
and generate a downloadable Excel report with unmatched payments.
""")

# -------------------------
# 1️⃣ Upload Tenant Excel
# -------------------------
tenant_file = st.file_uploader("Upload Tenant Excel", type=["xlsx", "xls"])
if tenant_file:
    # Let user select sheet if multiple
    xls = pd.ExcelFile(tenant_file)
    sheet_name = st.selectbox("Select sheet with tenant data", xls.sheet_names)
    tenants = pd.read_excel(xls, sheet_name=sheet_name)

    st.write("Columns detected in sheet:", list(tenants.columns))
    
    # Ask user to select the columns to use
    studio_col = st.selectbox("Select Studio Number column", tenants.columns)
    artist_col = st.selectbox("Select Artist Name column", tenants.columns)
    rent_col = st.selectbox("Select Expected Rent column", tenants.columns)
    
    # Keep only needed columns
    tenants = tenants[[studio_col, artist_col, rent_col]]
    tenants.columns = ["Studio", "Artist", "Expected Rent"]
    
    # Initialize balance column
    if "Balance" not in tenants.columns:
        tenants["Balance"] = 0.0

    st.subheader("Tenant List")
    st.dataframe(tenants)

# -------------------------
# 2️⃣ Upload Payment CSV
# -------------------------
payment_file = st.file_uploader("Upload Payments CSV", type="csv")
if payment_file:
    payments = pd.read_csv(payment_file)
    
    st.write("Columns detected in payment CSV:", list(payments.columns))
    
    # Ask user which columns to use
    amount_col = st.selectbox("Select payment amount column", payments.columns)
    name_col = st.selectbox("Select payer/artist name column", payments.columns)
    
    # Keep only needed columns
    payments = payments[[name_col, amount_col]]
    payments.columns = ["Payer", "Amount Paid"]
    
    # Filter only positive amounts (incoming payments)
    payments = payments[payments["Amount Paid"] > 0].copy()
    
    st.subheader("Payments Upload")
    st.dataframe(payments)

# -------------------------
# 3️⃣ Allocate Payments
# -------------------------
if tenant_file and payment_file:
    allocated_rows = []
    unmatched_rows = []
    
    # Set fuzzy matching threshold
    threshold = 80
    
    # Copy tenants to track balances
    tenants_copy = tenants.copy()
    
    # Go through each payment
    for _, pay_row in payments.iterrows():
        payer_name = str(pay_row["Payer"]).strip()
        amount = float(pay_row["Amount Paid"])
        
        # Use fuzzy matching on Artist names
        best_match, score = process.extractOne(payer_name, tenants_copy["Artist"])
        
        if score >= threshold:
            idx = tenants_copy[tenants_copy["Artist"] == best_match].index[0]
            
            expected = tenants_copy.at[idx, "Expected Rent"]
            balance = tenants_copy.at[idx, "Balance"]
            
            # Compute new balance
            new_balance = balance + amount - expected
            tenants_copy.at[idx, "Balance"] = new_balance
            
            # Determine status
            if new_balance == 0:
                status = "Paid in full ✅"
            elif new_balance > 0:
                status = f"Overpaid 💰 (+{new_balance:.2f})"
            else:
                status = f"Partial ⚠️ ({new_balance:.2f})"
            
            allocated_rows.append({
                "Studio": tenants_copy.at[idx, "Studio"],
                "Artist": best_match,
                "Expected Rent": expected,
                "Amount Paid": amount,
                "Balance": new_balance,
                "Status": status
            })
        else:
            # No match → add to unmatched
            unmatched_rows.append({
                "Payer": payer_name,
                "Amount Paid": amount
            })
    
    allocated_df = pd.DataFrame(allocated_rows)
    unmatched_df = pd.DataFrame(unmatched_rows)
    
    st.subheader("💡 Payment Allocation Summary")
    st.dataframe(allocated_df)

    if not unmatched_df.empty:
        st.subheader("⚠️ Unmatched Payments")
        st.dataframe(unmatched_df)
    
    # -------------------------
    # 4️⃣ Export Excel
    # -------------------------
    def to_excel(allocated, unmatched):
        output = BytesIO()
        writer = pd.ExcelWriter(output, engine="xlsxwriter")
        
        allocated.to_excel(writer, index=False, sheet_name="Allocated Payments")
        unmatched.to_excel(writer, index=False, sheet_name="Unmatched Payments")
        
        writer.save()
        processed_data = output.getvalue()
        return processed_data
    
    excel_data = to_excel(allocated_df, unmatched_df)
    
    st.download_button(
        label="📥 Download Allocated Payments Excel",
        data=excel_data,
        file_name="rent_allocation.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
