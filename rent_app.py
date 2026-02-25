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
from reportlab.lib import utils

# -----------------------------
# CONFIG
# -----------------------------

DATABASE_FILE = "rent_database.csv"
ALLOCATIONS_FILE = "allocations.csv"

EXPECTED_RENT = 500  # Adjust if needed


# -----------------------------
# INITIAL SETUP
# -----------------------------

if not os.path.exists(DATABASE_FILE):
    pd.DataFrame().to_csv(DATABASE_FILE, index=False)

if not os.path.exists(ALLOCATIONS_FILE):
    pd.DataFrame(columns=["Payment_ID", "Allocated_To", "Category"]).to_csv(
        ALLOCATIONS_FILE, index=False
    )


# -----------------------------
# LOAD DATA
# -----------------------------

def load_database():
    try:
        return pd.read_csv(DATABASE_FILE, parse_dates=["Date"])
    except:
        return pd.DataFrame()


def load_allocations():
    try:
        return pd.read_csv(ALLOCATIONS_FILE)
    except:
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

uploaded_file = st.sidebar.file_uploader("Upload monthly CSV", type=["csv"])

database = load_database()
allocations = load_allocations()

# -----------------------------
# UPLOAD & APPEND
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

        # Filter only incoming payments
        new_data = new_data[new_data["Amount"] > 0]

        if not database.empty:
            new_data = new_data[
                ~new_data["Payment_ID"].isin(database["Payment_ID"])
            ]

        database = pd.concat([database, new_data], ignore_index=True)
        save_database(database)

        st.success("New payments appended to database.")

# -----------------------------
# TENANTS SETUP
# -----------------------------

st.sidebar.header("Tenants")

default_tenants = {
    "Studio 1": "Anna Schmidt",
    "Studio 2": "Jonas Weber",
    "Studio 3": "Mira Klein",
    "Studio 4": "David Fischer",
}

tenant_df = pd.DataFrame(
    [(k, v) for k, v in default_tenants.items()],
    columns=["Studio", "Tenant"],
)

tenants = list(tenant_df["Tenant"])

# -----------------------------
# MATCH PAYMENTS
# -----------------------------

if not database.empty:
    database["Matched_Tenant"] = database.apply(
        lambda row: match_payment(row, tenants), axis=1
    )

    database = database.merge(
        allocations,
        on="Payment_ID",
        how="left",
    )

# -----------------------------
# SORTING
# -----------------------------

st.sidebar.header("Sorting")

sort_option = st.sidebar.selectbox(
    "Sort by",
    ["Date", "Tenant Name", "Studio"]
)

if sort_option == "Tenant Name":
    database = database.sort_values("Matched_Tenant")
elif sort_option == "Studio":
    database = database.merge(
        tenant_df, left_on="Matched_Tenant", right_on="Tenant", how="left"
    )
    database = database.sort_values("Studio")
else:
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
# UNMATCHED PAYMENTS
# -----------------------------

st.header("Unmatched Payments")

unmatched = database[
    database["Matched_Tenant"].isna()
    & database["Allocated_To"].isna()
]

if not unmatched.empty:
    for _, row in unmatched.iterrows():
        st.write(
            f"{row['Date'].date()} | {row['Amount']} € | {row['Description']}"
        )

        col1, col2 = st.columns(2)

        with col1:
            studio = st.selectbox(
                f"Allocate to studio",
                list(default_tenants.keys()),
                key=row["Payment_ID"],
            )

            if st.button("Allocate", key=row["Payment_ID"] + "_alloc"):
                new_alloc = pd.DataFrame(
                    [[row["Payment_ID"], studio, "Studio"]],
                    columns=["Payment_ID", "Allocated_To", "Category"],
                )
                allocations = pd.concat([allocations, new_alloc])
                save_allocations(allocations)
                st.rerun()

        with col2:
            if st.button("Mark as Other", key=row["Payment_ID"] + "_other"):
                new_alloc = pd.DataFrame(
                    [[row["Payment_ID"], "Other", "Other"]],
                    columns=["Payment_ID", "Allocated_To", "Category"],
                )
                allocations = pd.concat([allocations, new_alloc])
                save_allocations(allocations)
                st.rerun()

# -----------------------------
# UNDO ALLOCATION
# -----------------------------

st.header("Undo Allocation")

allocated = database[database["Allocated_To"].notna()]

if not allocated.empty:
    for _, row in allocated.iterrows():
        st.write(
            f"{row['Date'].date()} | {row['Amount']} € → {row['Allocated_To']}"
        )
        if st.button("Undo", key=row["Payment_ID"] + "_undo"):
            allocations = allocations[
                allocations["Payment_ID"] != row["Payment_ID"]
            ]
            save_allocations(allocations)
            st.rerun()

# -----------------------------
# OVERPAYMENT TRACKING
# -----------------------------

st.header("Over / Underpayment Tracking")

summary = []

for studio, tenant in default_tenants.items():
    tenant_payments = database[
        database["Matched_Tenant"] == tenant
    ]
    total_paid = tenant_payments["Amount"].sum()
    difference = total_paid - EXPECTED_RENT
    summary.append([studio, tenant, total_paid, difference])

summary_df = pd.DataFrame(
    summary,
    columns=["Studio", "Tenant", "Total Paid", "Difference"]
)

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
    table.setStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
    ])

    elements.append(table)
    doc.build(elements)
    return buffer.getvalue()

st.header("Export")

if not summary_df.empty:
    excel_file = export_excel(summary_df)
    pdf_file = export_pdf(summary_df)

    st.download_button(
        "Download Excel",
        excel_file,
        file_name="rent_overview.xlsx",
    )

    st.download_button(
        "Download PDF",
        pdf_file,
        file_name="rent_overview.pdf",
    )
