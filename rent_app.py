import streamlit as st
import pandas as pd
from datetime import datetime
from io import BytesIO

st.set_page_config(page_title="Studio Rent Tool", layout="wide")

st.title("Studio Rent Management Tool")

# ==========================
# FILE UPLOAD
# ==========================
tenants_file = st.file_uploader("Upload Tenant Excel (wide format)", type=["xlsx"])
bank_file = st.file_uploader("Upload Bank CSV", type=["csv"])

if tenants_file and bank_file:

    # ==========================
    # LOAD TENANTS (WIDE FORMAT)
    # ==========================
    tenants_raw = pd.read_excel(tenants_file)

    month_columns = [col for col in tenants_raw.columns if "-" in col]

    tenants_long = tenants_raw.melt(
        id_vars=["Studio", "Studio Order", "Artist Name"],
        value_vars=month_columns,
        var_name="Month",
        value_name="Rent Due"
    )

    tenants_long["Rent Due"] = pd.to_numeric(tenants_long["Rent Due"], errors="coerce").fillna(0)
    tenants_long["Month"] = pd.to_datetime(tenants_long["Month"], format="%b-%Y")

    # ==========================
    # LOAD BANK
    # ==========================
    bank = pd.read_csv(bank_file)
    bank["Date"] = pd.to_datetime(bank["Date"])
    bank["Amount"] = pd.to_numeric(bank["Amount"], errors="coerce").fillna(0)

    if "Verwendungszweck" not in bank.columns:
        bank["Verwendungszweck"] = ""

    # ==========================
    # BUILD LEDGER
    # ==========================
    ledger = tenants_long.copy()
    ledger["Allocated"] = 0.0
    ledger["Payment Details"] = [[] for _ in range(len(ledger))]

    unmatched_payments = []

    # ==========================
    # AUTO ALLOCATION
    # ==========================
    for _, payment in bank.iterrows():
        remaining = payment["Amount"]

        matches = ledger[
            (ledger["Artist Name"].str.lower() == str(payment["Name"]).lower())
            & (ledger["Allocated"] < ledger["Rent Due"])
        ].sort_values("Month")

        if len(matches) == 0:
            unmatched_payments.append(payment)
            continue

        for idx, row in matches.iterrows():
            outstanding = row["Rent Due"] - row["Allocated"]
            allocation = min(outstanding, remaining)

            if allocation > 0:
                ledger.at[idx, "Allocated"] += allocation
                ledger.at[idx, "Payment Details"].append(
                    (payment["Date"], allocation, payment["Amount"], payment["Verwendungszweck"])
                )
                remaining -= allocation

            if remaining <= 0:
                break

        if remaining > 0:
            unmatched_payments.append(payment)

    unmatched_payments = pd.DataFrame(unmatched_payments)

    ledger["Status"] = ledger.apply(
        lambda row: "Paid"
        if row["Allocated"] >= row["Rent Due"]
        else ("Partially Paid" if row["Allocated"] > 0 else "Unpaid"),
        axis=1
    )

    # ==========================
    # SESSION STATE
    # ==========================
    if "ledger" not in st.session_state:
        st.session_state.ledger = ledger

    if "unmatched_payments" not in st.session_state:
        st.session_state.unmatched_payments = unmatched_payments

    if "audit_log" not in st.session_state:
        st.session_state.audit_log = []

    ledger = st.session_state.ledger
    unmatched_payments = st.session_state.unmatched_payments
    audit_log = st.session_state.audit_log

    # ==========================
    # FUNCTIONS
    # ==========================
    def allocate_payment_to_artist(artist_name, amount, date, verwendungszweck):
        remaining = amount

        target_rows = ledger[
            (ledger["Artist Name"] == artist_name)
            & (ledger["Allocated"] < ledger["Rent Due"])
        ].sort_values("Month")

        for idx, row in target_rows.iterrows():
            outstanding = row["Rent Due"] - row["Allocated"]
            allocation = min(outstanding, remaining)

            if allocation > 0:
                ledger.at[idx, "Allocated"] += allocation
                ledger.at[idx, "Payment Details"].append(
                    (date, allocation, amount, verwendungszweck)
                )
                remaining -= allocation

            if remaining <= 0:
                break

    def undo_last_allocation():
        if len(audit_log) == 0:
            return

        last = audit_log.pop()
        artist = last["Artist"]
        amount = last["Amount"]

        rows = ledger[
            (ledger["Artist Name"] == artist)
            & (ledger["Allocated"] > 0)
        ].sort_values("Month", ascending=False)

        remaining = amount

        for idx, row in rows.iterrows():
            deduction = min(row["Allocated"], remaining)
            ledger.at[idx, "Allocated"] -= deduction
            remaining -= deduction

            if remaining <= 0:
                break

    # ==========================
    # TABS
    # ==========================
    tab1, tab2, tab3, tab4 = st.tabs(
        ["Ledger", "Summary", "Allocate Unmatched", "Audit Log"]
    )

    # ==========================
    # LEDGER TAB
    # ==========================
    with tab1:

        show_unpaid = st.checkbox("Show only unpaid / partially paid")

        display = ledger.copy()

        if show_unpaid:
            display = display[display["Status"] != "Paid"]

        display = display.sort_values(["Studio", "Studio Order", "Month"])

        display["Payment Details"] = display["Payment Details"].apply(
            lambda details: ", ".join(
                f"{alloc:.0f}/{total:.0f} ({date.strftime('%Y-%m-%d')}, {desc})"
                for date, alloc, total, desc in sorted(details, key=lambda x: x[0])
            ) if len(details) > 0 else ""
        )

        st.dataframe(display, use_container_width=True)

    # ==========================
    # SUMMARY TAB
    # ==========================
    with tab2:

        summary = ledger.groupby("Artist Name").agg(
            Total_Due=("Rent Due", "sum"),
            Total_Paid=("Allocated", "sum")
        )

        summary["Outstanding"] = summary["Total_Due"] - summary["Total_Paid"]

        st.dataframe(summary, use_container_width=True)

        output = BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            ledger.to_excel(writer, sheet_name="Ledger", index=False)
            summary.to_excel(writer, sheet_name="Summary")
            unmatched_payments.to_excel(writer, sheet_name="Unmatched", index=False)

        st.download_button(
            "Download Excel Report",
            output.getvalue(),
            file_name="studio_rent_report.xlsx"
        )

        if st.button("Undo Last Allocation"):
            undo_last_allocation()
            st.success("Last allocation undone")
            st.experimental_rerun()

    # ==========================
    # ALLOCATE UNMATCHED
    # ==========================
    with tab3:

        if len(unmatched_payments) == 0:
            st.success("No unmatched payments 🎉")
        else:
            artists = sorted(ledger["Artist Name"].unique())

            for i, payment in unmatched_payments.iterrows():
                st.markdown("---")
                st.write(payment)

                selected_artist = st.selectbox(
                    "Assign to Artist",
                    artists,
                    key=f"artist_{i}"
                )

                allocation_amount = st.number_input(
                    "Amount to allocate",
                    min_value=0.0,
                    max_value=float(payment["Amount"]),
                    value=float(payment["Amount"]),
                    key=f"amount_{i}"
                )

                if st.button("Allocate", key=f"allocate_{i}"):

                    allocate_payment_to_artist(
                        selected_artist,
                        allocation_amount,
                        payment["Date"],
                        payment.get("Verwendungszweck", "")
                    )

                    remaining = payment["Amount"] - allocation_amount

                    audit_log.append({
                        "Action": "Manual Allocation",
                        "Date": payment["Date"],
                        "Artist": selected_artist,
                        "Amount": allocation_amount,
                        "Verwendungszweck": payment.get("Verwendungszweck", "")
                    })

                    if remaining > 0:
                        unmatched_payments.at[i, "Amount"] = remaining
                    else:
                        unmatched_payments = unmatched_payments.drop(i)

                    st.session_state.unmatched_payments = unmatched_payments
                    st.success("Allocation completed")
                    st.experimental_rerun()

    # ==========================
    # AUDIT LOG
    # ==========================
    with tab4:
        if len(audit_log) == 0:
            st.info("No actions recorded yet.")
        else:
            st.dataframe(pd.DataFrame(audit_log), use_container_width=True)
