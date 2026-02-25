import streamlit as st
import pandas as pd
import os
from datetime import datetime
from io import BytesIO

# Excel export
from openpyxl import Workbook

# PDF export
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

# -----------------------------
# CONFIG
# -----------------------------
DATABASE_FILE = "rent_database.csv"
ALLOCATIONS_FILE = "allocations.csv"

# -----------------------------
# INITIAL SETUP
# -----------------------------
if not os.path.exists(DATABASE_FILE):
    pd.DataFrame(columns=["Date", "Amount", "Description", "Payment_ID"]).to_csv(DATABASE_FILE, index=False)

if not os.path.exists(ALLOCATIONS_FILE):
    pd.DataFrame(columns=["Payment_ID", "Allocated_To", "Category"]).to_csv(
        ALLOCATIONS_FILE, index=False
    )

# -----------------------------
# LOAD DATA
# -----------------------------
def load_database():
    try:
        df = pd.read_csv(DATABASE_FILE, parse_dates=["Date"])
        for col in ["Date", "Amount", "Description", "Payment_ID"]:
            if col not in df.columns:
                df[col] = pd.NA
        return df
    except Exception:
        return pd.DataFrame(columns=["Date", "Amount", "Description", "Payment_ID"])

def load_allocations():
    try:
        df = pd.read_csv(ALLOCATIONS_FILE)
        for col in ["Payment_ID", "Allocated_To", "Category"]:
            if col not in df.columns:
                df[col] = pd.NA
        return df
    except Exception:
        return pd.DataFrame(columns=["Payment_ID", "Allocated_To", "Category"])

def save_database(df):
    df.to_csv(DATABASE_FILE, index=False)

def save_allocations(df):
    df.to_csv(ALLOCATIONS_FILE, index=False)

# -----------------------------
# MATCHING LOGIC
# -----------------------------
def match_payment(row, tenants):
    for name in tenants:
        if name.lower() in str(row["Description"]).lower():
            return name
    return None

# -----------------------------
# STREAMLIT UI
# -----------------------------
st.title("🏢 Studio Rent Manager")

st.sidebar.header("Upload Banking CSV")
uploaded_file = st.sidebar.file_uploader("Upload monthly banking CSV", type=["csv"])

database = load_database()
allocations = load_allocations()

# -----------------------------
# UPLOAD & APPEND PAYMENTS
# -----------------------------
if uploaded_file:
    new_data = pd.read_csv(uploaded_file)
    required_cols = ["Date", "Amount", "Description"]
    if not all(col in new_data.columns for col in required_cols):
        st.error("CSV must contain: Date, Amount, Description")
    else:
        new_data["Date"] = pd.to_datetime(new_data["Date"])
        new_data["Payment_ID"] = (
            new_data["Date"].astype(str)
            + new_data["Amount"].astype(str)
            + new_data["Description"]
        )

        new_data = new_data[new_data["Amount"] > 0]  # only incoming payments

        if not database.empty:
            new_data = new_data[~new_data["Payment_ID"].isin(database["Payment_ID"])]

        database = pd.concat([database, new_data], ignore_index=True)
        save_database(database)
        st.success("New payments appended to database.")

# -----------------------------
# TENANTS SETUP
# -----------------------------
st.sidebar.header("Tenant List (Excel Upload)")

# Default tenants fallback
default_tenants = {
    "Studio 1": "Anna Schmidt",
    "Studio 2": "Jonas Weber",
    "Studio 3": "Mira Klein",
    "Studio 4": "David Fischer",
}

uploaded_tenants = st.sidebar.file_uploader("Upload tenant Excel file", type=["xlsx"])

months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

if uploaded_tenants:
    try:
        tenant_df = pd.read_excel(uploaded_tenants)
        required_cols = ["Studio", "Tenant"] + months
        if not all(col in tenant_df.columns for col in required_cols):
            st.error(f"Tenant Excel must contain columns: {', '.join(required_cols)}")
            tenant_df = pd.DataFrame(
                [(k, v, *[500]*12) for k,v in default_tenants.items()],
                columns=["Studio","Tenant"]+months
            )
    except Exception as e:
        st.error(f"Error reading tenant Excel: {e}")
        tenant_df = pd.DataFrame(
            [(k, v, *[500]*12) for k,v in default_tenants.items()],
            columns=["Studio","Tenant"]+months
        )
else:
    tenant_df = pd.DataFrame(
        [(k, v, *[500]*12) for k,v in default_tenants.items()],
        columns=["Studio","Tenant"]+months
    )

tenants = list(tenant_df["Tenant"])

# -----------------------------
# MATCH PAYMENTS
# -----------------------------
if not database.empty:
    database["Matched_Tenant"] = database.apply(lambda row: match_payment(row, tenants), axis=1)
    database = database.merge(allocations, on="Payment_ID", how="left")

# -----------------------------
# SORTING
# -----------------------------
st.sidebar.header("Sorting")
sort_option = st.sidebar.selectbox("Sort by", ["Date", "Tenant Name", "Studio"])

if not database.empty:
    if sort_option == "Tenant Name" and "Matched_Tenant" in database.columns:
        database = database.sort_values("Matched_Tenant")
    elif sort_option == "Studio" and "Matched_Tenant" in database.columns:
        database = database.merge(tenant_df, left_on="Matched_Tenant", right_on="Tenant", how="left")
        database = database.sort_values("Studio")
    elif sort_option == "Date" and "Date" in database.columns:
        database = database.sort_values("Date", ascending=False)

# -----------------------------
# DASHBOARD
# -----------------------------
st.header("Incoming Payments Overview")
if not database.empty:
    total_income = database["Amount"].sum()
    st.metric("Total Income", f"{total_income:.2f} €")
    st.dataframe(database)

# -----------------------------
# UNMATCHED PAYMENTS (Batch Allocation Form)
# -----------------------------
st.header("Unmatched Payments")

if not database.empty:
    unmatched = database[database.get("Matched_Tenant").isna() & database.get("Allocated_To").isna()]
else:
    unmatched = pd.DataFrame()

if not unmatched.empty:
    st.write("Allocate unmatched payments to studios or mark as Other.")

    with st.form("allocate_form"):
        allocation_choices = {}
        for idx, row in unmatched.iterrows():
            st.write(f"{row['Date'].date() if pd.notna(row['Date']) else 'No Date'} | {row['Amount']} € | {row['Description']}")
            allocation_choices[row["Payment_ID"]] = st.selectbox(
                f"Allocate payment {row['Payment_ID']}", 
                options=list(tenant_df["Studio"]) + ["Other"], 
                index=0
            )
        
        submit_alloc = st.form_submit_button("Apply Allocations")
        
        if submit_alloc:
            new_alloc_list = []
            for pid, studio in allocation_choices.items():
                category = "Studio" if studio != "Other" else "Other"
                new_alloc_list.append([pid, studio, category])
            
            if new_alloc_list:
                new_alloc_df = pd.DataFrame(new_alloc_list, columns=["Payment_ID", "Allocated_To", "Category"])
                allocations = pd.concat([allocations, new_alloc_df], ignore_index=True)
                save_allocations(allocations)
                st.success(f"{len(new_alloc_list)} payment allocations saved.")
                st.experimental_rerun()

# -----------------------------
# UNDO ALLOCATION
# -----------------------------
st.header("Undo Allocation")
allocated = pd.DataFrame()
if not database.empty:
    allocated = database[database.get("Allocated_To").notna()]

if not allocated.empty:
    for _, row in allocated.iterrows():
        st.write(f"{row['Date'].date() if pd.notna(row['Date']) else 'No Date'} | {row['Amount']} € → {row['Allocated_To']}")
        if st.button("Undo", key=row["Payment_ID"]+"_undo"):
            allocations = allocations[allocations["Payment_ID"] != row["Payment_ID"]]
            save_allocations(allocations)
            st.experimental_rerun()

# -----------------------------
# OVERPAYMENT TRACKING
# -----------------------------
st.header("Over / Underpayment Tracking")

summary = []

if not database.empty:
    database["Month"] = database["Date"].dt.strftime("%b")  # e.g., 'Jan', 'Feb', ...

for _, tenant_row in tenant_df.iterrows():
    studio = tenant_row["Studio"]
    tenant = tenant_row["Tenant"]
    
    tenant_payments = database[database.get("Matched_Tenant") == tenant] if not database.empty else pd.DataFrame()
    
    total_paid = tenant_payments["Amount"].sum() if not tenant_payments.empty else 0
    expected_total = 0
    
    if not tenant_payments.empty:
        for _, pay in tenant_payments.iterrows():
            month_col = pay["Month"]
            if month_col in tenant_row:
                expected_total += tenant_row[month_col]
    
    difference = total_paid - expected_total
    summary.append([studio, tenant, total_paid, expected_total, difference])

summary_df = pd.DataFrame(summary, columns=["Studio","Tenant","Total Paid","Expected Rent","Difference"])
st.dataframe(summary_df)

# -----------------------------
# EXPORT FUNCTIONS
# -----------------------------
def export_excel(df):
    output = BytesIO()
    wb = Workbook()
    ws = wb.active
    ws.title = "Rent Overview"
    ws.append(list(df.columns))
    for row in df.itertuples(index=False):
        ws.append(row)
    wb.save(output)
    return output.getvalue()

def export_pdf(df):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer)
    elements = []
    style = getSampleStyleSheet()
    elements.append(Paragraph("Studio Rent Overview", style["Heading1"]))
    elements.append(Spacer(1, 12))
    data = [list(df.columns)] + df.values.tolist()
    table = Table(data)
    table.setStyle([("BACKGROUND",(0,0),(-1,0),colors.grey),("GRID",(0,0),(-1,-1),0.5,colors.black)])
    elements.append(table)
    doc.build(elements)
    return buffer.getvalue()

st.header("Export")
if not summary_df.empty:
    excel_file = export_excel(summary_df)
    pdf_file = export_pdf(summary_df)
    st.download_button("Download Excel", excel_file, file_name="rent_overview.xlsx")
    st.download_button("Download PDF", pdf_file, file_name="rent_overview.pdf")
