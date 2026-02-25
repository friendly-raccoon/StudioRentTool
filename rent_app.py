import streamlit as st
import pandas as pd
import pickle
import os
from io import BytesIO
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import pagesizes

st.set_page_config(layout="wide")
st.title("Studio Rent Management")

STATE_FILE = "rent_state.pkl"

# -------------------------
# Persistence
# -------------------------

def save_state():
    with open(STATE_FILE, "wb") as f:
        pickle.dump({
            "ledger": st.session_state.ledger,
            "unmatched": st.session_state.unmatched_payments,
            "audit": st.session_state.audit_log,
            "other": st.session_state.other_payments
        }, f)

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "rb") as f:
            data = pickle.load(f)
            st.session_state.ledger = data["ledger"]
            st.session_state.unmatched_payments = data["unmatched"]
            st.session_state.audit_log = data["audit"]
            st.session_state.other_payments = data.get("other", [])

def export_ledger_excel():
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        st.session_state.ledger.to_excel(writer, index=False, sheet_name="Ledger")
    return output.getvalue()


def export_summary_excel(summary_df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        summary_df.to_excel(writer, sheet_name="Summary")
    return output.getvalue()


def export_other_excel():
    output = BytesIO()
    other_df = pd.DataFrame(st.session_state.other_payments)
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        other_df.to_excel(writer, index=False, sheet_name="Other Payments")
    return output.getvalue()


def export_summary_pdf(summary_df):

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=pagesizes.A4)
    elements = []

    styles = getSampleStyleSheet()
    elements.append(Paragraph("Studio Rent Summary", styles["Heading1"]))
    elements.append(Spacer(1, 20))

    data = [summary_df.reset_index().columns.tolist()] + summary_df.reset_index().values.tolist()

    table = Table(data)
    table.setStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
    ])

    elements.append(table)
    doc.build(elements)

    return buffer.getvalue()
    
# -------------------------
# Reset
# -------------------------

if st.button("🔄 Reset System"):
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)
    st.session_state.clear()
    st.rerun()

# -------------------------
# File Upload
# -------------------------

ledger_file = st.file_uploader("Upload Rent Ledger Excel", type=["xlsx"])
bank_file = st.file_uploader("Upload Bank CSV", type=["csv"])

if ledger_file and bank_file:

    if "ledger" not in st.session_state:

        # Load ledger
        ledger = pd.read_excel(ledger_file)
        ledger["Allocated"] = 0.0
        ledger["Payment Details"] = [[] for _ in range(len(ledger))]
        ledger["Credit"] = 0.0

        # -------------------------
        # Parse German Bank CSV
        # -------------------------

        bank = pd.read_csv(
            bank_file,
            sep="\t",
            encoding="ISO-8859-1"
        )

        bank = bank[[
            "Buchungstag",
            "Betrag",
            "Beguenstigter/Zahlungspflichtiger",
            "Verwendungszweck"
        ]].copy()

        bank = bank.rename(columns={
            "Buchungstag": "Date",
            "Betrag": "Amount",
            "Beguenstigter/Zahlungspflichtiger": "Name"
        })

        bank["Date"] = pd.to_datetime(bank["Date"], dayfirst=True)
        bank["Amount"] = (
            bank["Amount"]
            .astype(str)
            .str.replace(".", "", regex=False)
            .str.replace(",", ".", regex=False)
        )
        bank["Amount"] = pd.to_numeric(bank["Amount"], errors="coerce")

        # -------------------------
        # Filter only incoming payments
        # -------------------------

        bank = bank[bank["Amount"] > 0]

        unmatched_payments = []
        other_payments = []
        audit_log = []

        # -------------------------
        # Auto-Match by Name
        # -------------------------

        for _, payment in bank.iterrows():

            amount = payment["Amount"]
            name = str(payment["Name"])
            date = payment["Date"]
            purpose = payment["Verwendungszweck"]

            matched_rows = ledger[
                ledger["Artist Name"].str.contains(name, case=False, na=False)
            ]

            if matched_rows.empty:
                unmatched_payments.append(payment)
                continue

            remaining = amount

            rows = matched_rows[
                matched_rows["Allocated"] < matched_rows["Rent Due"]
            ].sort_values("Month")

            for idx, row in rows.iterrows():

                outstanding = row["Rent Due"] - row["Allocated"]
                allocation = min(outstanding, remaining)

                if allocation > 0:
                    ledger.at[idx, "Allocated"] += allocation
                    ledger.at[idx, "Payment Details"].append(
                        (date, allocation, amount, purpose)
                    )
                    remaining -= allocation

                if remaining <= 0:
                    break

            # Overpayment → Credit
            if remaining > 0:
                ledger.loc[
                    ledger["Artist Name"] == row["Artist Name"],
                    "Credit"
                ] += remaining

        ledger["Status"] = ledger.apply(
            lambda row: "Paid"
            if row["Allocated"] >= row["Rent Due"]
            else ("Partially Paid" if row["Allocated"] > 0 else "Unpaid"),
            axis=1
        )

        st.session_state.ledger = ledger
        st.session_state.unmatched_payments = unmatched_payments
        st.session_state.audit_log = audit_log
        st.session_state.other_payments = other_payments

        save_state()

    else:
        load_state()

# -------------------------
# Tabs
# -------------------------

if "ledger" in st.session_state:

    ledger = st.session_state.ledger

    tab1, tab2, tab3 = st.tabs(["Ledger", "Unmatched", "Summary"])

    # -------------------------
    # Ledger
    # -------------------------

    with tab1:
        display_ledger = ledger.copy()

    if "Payment Details" in display_ledger.columns:
        display_ledger["Payment Details"] = display_ledger["Payment Details"].astype(str)

st.dataframe(display_ledger)

    # -------------------------
    # Unmatched
    # -------------------------

    with tab2:

        unmatched = st.session_state.unmatched_payments

        if unmatched:

            for i, payment in enumerate(unmatched):

                st.write(
                    f"{payment['Date']} | {payment['Name']} | {payment['Amount']}€"
                )

                col1, col2, col3 = st.columns(3)

                with col1:
                    artist = st.selectbox(
                        "Allocate to Artist",
                        ledger["Artist Name"].unique(),
                        key=f"artist_{i}"
                    )

                with col2:
                    if st.button("Allocate", key=f"alloc_{i}"):

                        amount = payment["Amount"]
                        date = payment["Date"]
                        purpose = payment["Verwendungszweck"]

                        remaining = amount

                        rows = ledger[
                            (ledger["Artist Name"] == artist)
                            & (ledger["Allocated"] < ledger["Rent Due"])
                        ].sort_values("Month")

                        for idx, row in rows.iterrows():
                            outstanding = row["Rent Due"] - row["Allocated"]
                            allocation = min(outstanding, remaining)

                            if allocation > 0:
                                ledger.at[idx, "Allocated"] += allocation
                                ledger.at[idx, "Payment Details"].append(
                                    (date, allocation, amount, purpose)
                                )
                                remaining -= allocation

                            if remaining <= 0:
                                break

                        if remaining > 0:
                            ledger.loc[
                                ledger["Artist Name"] == artist,
                                "Credit"
                            ] += remaining

                        st.session_state.unmatched_payments.pop(i)
                        save_state()
                        st.rerun()

                with col3:
                    if st.button("Mark as Other", key=f"other_{i}"):

                        st.session_state.other_payments.append(payment)
                        st.session_state.unmatched_payments.pop(i)
                        save_state()
                        st.rerun()

        else:
            st.success("No unmatched payments 🎉")

    # -------------------------
    # Summary
    # -------------------------

    with tab3:

        summary = ledger.groupby("Artist Name").agg(
            Total_Due=("Rent Due", "sum"),
            Total_Paid=("Allocated", "sum"),
            Credit=("Credit", "max")
        )

        summary["Outstanding"] = summary["Total_Due"] - summary["Total_Paid"]

        st.dataframe(summary)

        st.write("### Other Payments")
        st.write(st.session_state.other_payments)
