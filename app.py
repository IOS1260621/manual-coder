import streamlit as st
import pandas as pd
import json
import re
from pathlib import Path
from datetime import date, datetime, timedelta
from calendar import monthrange


st.set_page_config(
    page_title="Employee Scheduling Planner",
    layout="wide"
)

st.title("Employee Scheduling Planner")

st.markdown(
    """
    <style>
    div[data-testid="stDataFrame"] {
        --gdg-header-font-style: 900 20px "Source Sans Pro", sans-serif !important;
        --gdg-font-size: 15px !important;
    }

    div[data-testid="stDataFrame"] [role="columnheader"],
    div[data-testid="stDataFrame"] [data-testid="stDataFrameResizableHeader"] {
        font-size: 1.2rem !important;
        font-weight: 900 !important;
    }

    div[data-testid="stDataFrame"] [role="columnheader"] p,
    div[data-testid="stDataFrame"] [role="columnheader"] span,
    div[data-testid="stDataFrame"] [data-testid="stDataFrameResizableHeader"] p,
    div[data-testid="stDataFrame"] [data-testid="stDataFrameResizableHeader"] span {
        font-size: 1.2rem !important;
        font-weight: 900 !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)

SCHEDULE_SAVE_DIR = Path("saved_schedules")
SCHEDULE_SAVE_DIR.mkdir(exist_ok=True)


# -----------------------------
# Helper Functions
# -----------------------------

def calculate_shift_hours(shift_time):
    """
    Converts military shift time into hours.

    Examples:
    0700-1900 = 12.0
    1900-0700 = 12.0 because it crosses midnight
    0730-1600 = 8.5
    """

    if shift_time is None:
        return 0.0

    shift_time = str(shift_time).strip().replace(" ", "")

    if shift_time == "":
        return 0.0

    # Accepts 0700-1900 or 07:00-19:00
    pattern = r"^(\d{1,2}:?\d{2})-(\d{1,2}:?\d{2})$"
    match = re.match(pattern, shift_time)

    if not match:
        return 0.0

    start_text, end_text = match.groups()

    start_text = start_text.replace(":", "")
    end_text = end_text.replace(":", "")

    # Allow 700-1900 and convert to 0700-1900
    start_text = start_text.zfill(4)
    end_text = end_text.zfill(4)

    try:
        start = datetime.strptime(start_text, "%H%M")
        end = datetime.strptime(end_text, "%H%M")

        # Overnight shift
        if end < start:
            end += timedelta(days=1)

        hours = (end - start).total_seconds() / 3600
        return round(hours, 2)

    except ValueError:
        return 0.0


def clean_weekly_schedule(df):
    """
    Applies your rules:
    1. If Status is not Scheduled, all non-status fields become blank.
    2. If Status is not Scheduled, Shift Hours becomes 0.
    3. If working, Shift Hours is calculated from Shift Time.
    """

    df = df.copy()

    for index, row in df.iterrows():
        status = str(row.get("Status", "")).strip()
        shift_time = str(row.get("Shift Time", "")).strip()

        if status != "Scheduled":
            df.at[index, "Shift Time"] = ""
            df.at[index, "Shift Hours"] = 0.0
            df.at[index, "Modality"] = ""
            df.at[index, "Site / Hospital"] = ""
            df.at[index, "Room Assignment"] = ""
            df.at[index, "Call Assignment"] = ""
            df.at[index, "Notes"] = ""
        else:
            df.at[index, "Shift Hours"] = calculate_shift_hours(shift_time)

    return df


def fill_first_values_to_rest_of_week(df):
    """
    Button action:
    - Finds the first working row with a Shift Time.
    - Copies that Shift Time to the rest of the working days.
    - Clears Shift Time on OFF days.
    - Calculates Shift Hours.
    - Finds the first working row with a Modality.
    - Copies Modality to the rest of the working days.
    """

    df = df.copy()

    first_shift_time = ""
    first_modality = ""

    for _, row in df.iterrows():
        status = str(row.get("Status", "")).strip()
        shift_time = str(row.get("Shift Time", "")).strip()

        if status == "Scheduled" and shift_time:
            first_shift_time = shift_time
            break

    for _, row in df.iterrows():
        status = str(row.get("Status", "")).strip()
        modality = str(row.get("Modality", "")).strip()

        if status == "Scheduled" and modality and modality != "None":
            first_modality = modality
            break

    for index, row in df.iterrows():
        status = str(row.get("Status", "")).strip()

        if status != "Scheduled":
            df.at[index, "Shift Time"] = ""
            df.at[index, "Shift Hours"] = 0.0
            df.at[index, "Modality"] = ""
            df.at[index, "Site / Hospital"] = ""
            df.at[index, "Room Assignment"] = ""
            df.at[index, "Call Assignment"] = ""
            df.at[index, "Notes"] = ""

        else:
            if first_shift_time:
                df.at[index, "Shift Time"] = first_shift_time

            current_shift_time = str(df.at[index, "Shift Time"]).strip()
            df.at[index, "Shift Hours"] = calculate_shift_hours(current_shift_time)

            if first_modality:
                df.at[index, "Modality"] = first_modality

    return df


def get_month_dates(year, month):
    days_in_month = monthrange(year, month)[1]
    return [date(year, month, day) for day in range(1, days_in_month + 1)]


def get_week_ranges(year, month):
    month_dates = get_month_dates(year, month)
    weeks = [month_dates[i:i + 7] for i in range(0, min(28, len(month_dates)), 7)]

    if len(month_dates) > 28:
        weeks.append(month_dates[28:])

    return weeks


def sanitize_schedule_name(schedule_name):
    schedule_name = str(schedule_name).strip()
    schedule_name = re.sub(r"[^A-Za-z0-9._ -]+", "_", schedule_name)
    return schedule_name.replace(" ", "_")


def get_saved_schedule_names():
    return sorted(path.stem for path in SCHEDULE_SAVE_DIR.glob("*.json"))


def save_current_schedule(schedule_name):
    safe_name = sanitize_schedule_name(schedule_name)

    if not safe_name:
        return False, "Please choose a schedule name to save."

    payload = {
        "employees": st.session_state.employees,
        "schedule": st.session_state.schedule,
        "saved_at": datetime.now().isoformat()
    }

    save_path = SCHEDULE_SAVE_DIR / f"{safe_name}.json"

    with save_path.open("w", encoding="utf-8") as file_handle:
        json.dump(payload, file_handle, indent=2, ensure_ascii=False)

    return True, f"Saved schedule to {safe_name}."


def load_saved_schedule(schedule_name):
    safe_name = sanitize_schedule_name(schedule_name)
    load_path = SCHEDULE_SAVE_DIR / f"{safe_name}.json"

    if not load_path.exists():
        return False, f"Saved schedule {safe_name} was not found."

    with load_path.open("r", encoding="utf-8") as file_handle:
        payload = json.load(file_handle)

    st.session_state.employees = payload.get("employees", {})
    st.session_state.schedule = payload.get("schedule", {})

    employee_names = list(st.session_state.employees.keys())
    st.session_state.selected_employee = employee_names[0] if employee_names else ""

    return True, f"Loaded schedule {safe_name}."


def create_blank_day_row(day_date, employee_info):
    return {
        "Day": day_date.day,
        "Date": day_date.strftime("%m/%d/%Y"),
        "ISO Date": day_date.isoformat(),
        "Weekday": day_date.strftime("%A"),
        "Status": "Scheduled",
        "Shift Time": "",
        "Shift Hours": 0.0,
        "Modality": employee_info.get("Default Modality", ""),
        "Site / Hospital": employee_info.get("Default Site", ""),
        "Room Assignment": "",
        "Call Assignment": "",
        "Notes": ""
    }


def get_weekly_df(employee_name, week_dates):
    employee_info = st.session_state.employees[employee_name]
    rows = []

    for day_date in week_dates:
        iso_date = day_date.isoformat()

        if iso_date in st.session_state.schedule.get(employee_name, {}):
            row = st.session_state.schedule[employee_name][iso_date].copy()
        else:
            row = create_blank_day_row(day_date, employee_info)

        rows.append(row)

    return pd.DataFrame(rows)


def save_weekly_df(employee_name, df):
    df = clean_weekly_schedule(df)

    if employee_name not in st.session_state.schedule:
        st.session_state.schedule[employee_name] = {}

    for _, row in df.iterrows():
        iso_date = row["ISO Date"]

        st.session_state.schedule[employee_name][iso_date] = {
            "Day": row["Day"],
            "Date": row["Date"],
            "ISO Date": row["ISO Date"],
            "Weekday": row["Weekday"],
            "Status": row["Status"],
            "Shift Time": row["Shift Time"],
            "Shift Hours": row["Shift Hours"],
            "Modality": row["Modality"],
            "Site / Hospital": row["Site / Hospital"],
            "Room Assignment": row["Room Assignment"],
            "Call Assignment": row["Call Assignment"],
            "Notes": row["Notes"]
        }

    return df


def build_monthly_schedule_table(year, month):
    month_dates = get_month_dates(year, month)
    table_rows = []
    day_columns = []

    for employee_name, employee_info in st.session_state.employees.items():
        row = {
            "Name": employee_name
        }

        for day_date in month_dates:
            iso_date = day_date.isoformat()
            column_name = day_date.strftime("%a %m/%d")
            day_columns.append(column_name)

            schedule_day = st.session_state.schedule.get(employee_name, {}).get(iso_date)

            cell_lines = []

            if schedule_day and schedule_day.get("Status") == "Scheduled":
                shift_time = schedule_day.get("Shift Time", "")
                modality = schedule_day.get("Modality", "")
                room = schedule_day.get("Room Assignment", "")
                call = schedule_day.get("Call Assignment", "")

                if shift_time:
                    cell_lines.append(shift_time)

                if modality:
                    cell_lines.append(modality)

                if room:
                    cell_lines.append(room)

                if call:
                    cell_lines.append(f"Call: {call}")

            row[column_name] = "\n".join(cell_lines)

        row["FTE"] = employee_info.get("FTE", "")
        row["Weekend Group"] = employee_info.get("Weekend Group", "")
        table_rows.append(row)

    if not table_rows:
        return pd.DataFrame(columns=["Name", "FTE", "Weekend Group"])

    column_order = ["Name"] + list(dict.fromkeys(day_columns)) + ["FTE", "Weekend Group"]
    return pd.DataFrame(table_rows)[column_order]


def build_weekly_schedule_table(week_dates):
    table_rows = []
    day_columns = []

    for employee_name, employee_info in st.session_state.employees.items():
        row = {
            "Name": employee_name
        }
        total_hours = 0.0

        for day_date in week_dates:
            iso_date = day_date.isoformat()
            column_name = day_date.strftime("%a %m/%d")
            day_columns.append(column_name)

            schedule_day = st.session_state.schedule.get(employee_name, {}).get(iso_date)

            cell_lines = []

            if schedule_day and schedule_day.get("Status") == "Scheduled":
                shift_time = schedule_day.get("Shift Time", "")
                modality = schedule_day.get("Modality", "")
                room = schedule_day.get("Room Assignment", "")
                call = schedule_day.get("Call Assignment", "")
                shift_hours = schedule_day.get("Shift Hours", calculate_shift_hours(shift_time))

                try:
                    total_hours += float(shift_hours)
                except (TypeError, ValueError):
                    total_hours += 0.0

                if shift_time:
                    cell_lines.append(shift_time)

                if modality:
                    cell_lines.append(modality)

                if room:
                    cell_lines.append(room)

                if call:
                    cell_lines.append(f"Call: {call}")

            row[column_name] = "\n".join(cell_lines)

        row["Total Hours"] = round(total_hours, 2)
        row["FTE"] = employee_info.get("FTE", "")
        row["Weekend Group"] = employee_info.get("Weekend Group", "")
        table_rows.append(row)

    if not table_rows:
        return pd.DataFrame(columns=["Name", "Total Hours", "FTE", "Weekend Group"])

    column_order = ["Name"] + list(dict.fromkeys(day_columns)) + ["Total Hours", "FTE", "Weekend Group"]
    return pd.DataFrame(table_rows)[column_order]


def build_weekly_assignment_coverage_table(week_dates):
    rows = []

    for day_date in week_dates:
        if day_date.weekday() >= 5:
            required_assignments = {"ER", "Main"}
        else:
            required_assignments = {"2", "ER", "Main"}

        iso_date = day_date.isoformat()
        covered_assignments = set()
        assignment_counts = {"Main": 0, "2": 0, "ER": 0}

        for employee_name in st.session_state.employees.keys():
            schedule_day = st.session_state.schedule.get(employee_name, {}).get(iso_date)

            if schedule_day and schedule_day.get("Status") == "Scheduled":
                assignment = str(schedule_day.get("Room Assignment", "")).strip()

                if assignment:
                    covered_assignments.add(assignment)

                if assignment in assignment_counts:
                    assignment_counts[assignment] += 1

        rows.append({
            "Day": day_date.strftime("%A"),
            "Date": day_date.strftime("%m/%d/%Y"),
            "Main": assignment_counts["Main"],
            "2": assignment_counts["2"],
            "ER": assignment_counts["ER"],
            "All Covered": required_assignments.issubset(covered_assignments)
        })

    return pd.DataFrame(rows)


# -----------------------------
# Session State
# -----------------------------

if "employees" not in st.session_state:
    st.session_state.employees = {}

if "schedule" not in st.session_state:
    st.session_state.schedule = {}

if "save_schedule_target" not in st.session_state:
    st.session_state.save_schedule_target = "New Schedule"

if "save_schedule_name" not in st.session_state:
    st.session_state.save_schedule_name = ""

if "load_schedule_target" not in st.session_state:
    st.session_state.load_schedule_target = ""

saved_schedule_names = get_saved_schedule_names()

if st.session_state.save_schedule_target not in (["New Schedule"] + saved_schedule_names):
    st.session_state.save_schedule_target = "New Schedule"

if saved_schedule_names and st.session_state.load_schedule_target not in saved_schedule_names:
    st.session_state.load_schedule_target = saved_schedule_names[0]

top_spacer_col, top_controls_col = st.columns([0.66, 0.34])

with top_controls_col:
    st.markdown("**Schedule Saves**")

    save_options = ["New Schedule"] + saved_schedule_names
    save_target = st.selectbox(
        "Save current schedule as",
        save_options,
        key="save_schedule_target",
        label_visibility="collapsed"
    )

    if save_target == "New Schedule":
        save_name = st.text_input(
            "New schedule name",
            placeholder="Enter a schedule name",
            key="save_schedule_name",
            label_visibility="collapsed"
        )
    else:
        save_name = save_target
        st.session_state.save_schedule_name = save_target

    if st.button("Save Current Schedule", use_container_width=True):
        success, message = save_current_schedule(save_name)
        if success:
            st.success(message)
            st.rerun()
        else:
            st.error(message)

    if saved_schedule_names:
        load_target = st.selectbox(
            "Load saved schedule",
            saved_schedule_names,
            key="load_schedule_target",
            label_visibility="collapsed"
        )

        if st.button("Load Selected Schedule", use_container_width=True):
            success, message = load_saved_schedule(load_target)
            if success:
                st.success(message)
                st.rerun()
            else:
                st.error(message)
    else:
        st.caption("No saved schedules yet.")


# -----------------------------
# Sidebar: Month and Employees
# -----------------------------

st.sidebar.header("Schedule Setup")

today = date.today()

selected_year = st.sidebar.number_input(
    "Year",
    min_value=2024,
    max_value=2035,
    value=today.year
)

selected_month = st.sidebar.number_input(
    "Month",
    min_value=1,
    max_value=12,
    value=today.month
)

st.sidebar.divider()

st.sidebar.header("Add Employee")

with st.sidebar.form("add_employee_form"):
    new_name = st.text_input("Employee Name")
    new_fte = st.text_input("FTE", placeholder="Example: 1.0")
    new_weekend_group = st.text_input("Weekend Group", placeholder="Example: A")
    new_default_site = st.text_input("Default Site", placeholder="Example: punchbowl")
    new_default_modality = st.selectbox(
        "Default Modality",
        ["X-Ray", "CT", "MRI", "Ultra Sound", "IR"]
    )

    add_employee_button = st.form_submit_button("Add Employee")

    if add_employee_button:
        if new_name.strip() == "":
            st.sidebar.warning("Please enter an employee name.")
        else:
            employee_name = new_name.strip()

            st.session_state.employees[employee_name] = {
                "FTE": new_fte.strip(),
                "Weekend Group": new_weekend_group.strip(),
                "Default Site": new_default_site.strip(),
                "Default Modality": new_default_modality.strip()
            }

            if employee_name not in st.session_state.schedule:
                st.session_state.schedule[employee_name] = {}

            st.session_state.selected_employee = employee_name
            st.sidebar.success(f"Added {employee_name}")
            st.rerun()


if len(st.session_state.employees) == 0:
    st.info("Add an employee in the sidebar to start creating the schedule.")
    st.stop()


# -----------------------------
# Main Controls
# -----------------------------

week_ranges = get_week_ranges(selected_year, selected_month)
week_labels = [
    f"Week {i + 1}: {week[0].strftime('%m/%d/%Y')} - {week[-1].strftime('%m/%d/%Y')}"
    for i, week in enumerate(week_ranges)
]

if "selected_week_label" not in st.session_state:
    st.session_state.selected_week_label = week_labels[0] if week_labels else ""

if st.session_state.selected_week_label not in week_labels:
    st.session_state.selected_week_label = week_labels[0] if week_labels else ""

st.subheader("Select Week")

if week_labels:
    week_button_columns = st.columns(len(week_labels))

    for index, week_label in enumerate(week_labels):
        button_type = "primary" if week_label == st.session_state.selected_week_label else "secondary"

        with week_button_columns[index]:
            if st.button(week_label, use_container_width=True, type=button_type, key=f"week_button_{index}"):
                st.session_state.selected_week_label = week_label
                st.rerun()

selected_week_label = st.session_state.selected_week_label
selected_week_index = week_labels.index(selected_week_label)
selected_week_dates = week_ranges[selected_week_index]

employee_names = list(st.session_state.employees.keys())

if "selected_employee" not in st.session_state:
    st.session_state.selected_employee = employee_names[0] if employee_names else ""

if st.session_state.selected_employee not in employee_names:
    st.session_state.selected_employee = employee_names[0] if employee_names else ""

selected_employee = st.selectbox(
    "Select Employee to Edit",
    employee_names,
    index=employee_names.index(st.session_state.selected_employee) if st.session_state.selected_employee in employee_names else 0,
    key="selected_employee"
)

st.subheader(selected_week_label)

st.info(
    "Enter one Shift Time and one Modality in any working row, then click "
    "'Fill First Shift Time and Modality to Rest of Week'. OFF days will stay blank."
)


# -----------------------------
# Weekly Editor
# -----------------------------

weekly_df = get_weekly_df(selected_employee, selected_week_dates)

display_df = weekly_df.drop(columns=["ISO Date"])

edited_week_df = st.data_editor(
    display_df,
    use_container_width=True,
    hide_index=True,
    num_rows="fixed",
    disabled=["Day", "Date", "Weekday", "Shift Hours"],
    column_config={
        "Status": st.column_config.SelectboxColumn(
            "Status",
            options=["Scheduled", "OFF", "PTO", "SICK"],
            required=True
        ),
        "Shift Time": st.column_config.TextColumn(
            "Shift Time",
            help="Use military time format. Example: 0700-1900"
        ),
        "Shift Hours": st.column_config.NumberColumn(
            "Shift Hours",
            help="Automatically calculated from Shift Time",
            min_value=0.0,
            max_value=24.0,
            step=0.25
        ),
        "Modality": st.column_config.SelectboxColumn(
            "Modality",
            options=["", "X-Ray", "CT", "MRI", "Ultrasound"],
            help="Example: X-Ray, CT, MRI, Ultrasound"
        ),
        "Site / Hospital": st.column_config.SelectboxColumn(
            "Site",
            options=["", "PB", "West"]
        ),
        "Room Assignment": st.column_config.TextColumn(
            "Assignment"
        ),
        "Call Assignment": st.column_config.TextColumn(
            "Call Assignment"
        ),
        "Notes": st.column_config.TextColumn(
            "Notes"
        )
    }
)

edited_week_df["ISO Date"] = weekly_df["ISO Date"]


# -----------------------------
# Buttons
# -----------------------------

button_col1, button_col2, button_col3 = st.columns(3)

with button_col1:
    if st.button("🔁 Fill First Shift Time and Modality to Rest of Week", use_container_width=True):
        filled_df = fill_first_values_to_rest_of_week(edited_week_df)
        save_weekly_df(selected_employee, filled_df)
        st.success("Filled working days, cleared OFF days, and calculated shift hours.")
        st.rerun()

with button_col2:
    if st.button("💾 Save Weekly Schedule", use_container_width=True):
        saved_df = save_weekly_df(selected_employee, edited_week_df)
        st.success("Weekly schedule saved. Shift hours recalculated.")
        st.rerun()

with button_col3:
    if st.button("🧹 Clear This Week", use_container_width=True):
        for day_date in selected_week_dates:
            iso_date = day_date.isoformat()

            if iso_date in st.session_state.schedule.get(selected_employee, {}):
                del st.session_state.schedule[selected_employee][iso_date]

        st.success("This week was cleared for the selected employee.")
        st.rerun()


# -----------------------------
# Copy Previous Week
# -----------------------------

if st.button("📋 Copy Previous Week to This Week", use_container_width=True):
    for day_date in selected_week_dates:
        current_iso = day_date.isoformat()
        previous_iso = (day_date - timedelta(days=7)).isoformat()

        previous_day = st.session_state.schedule.get(selected_employee, {}).get(previous_iso)

        if previous_day:
            copied_day = previous_day.copy()
            copied_day["Day"] = day_date.day
            copied_day["Date"] = day_date.strftime("%m/%d/%Y")
            copied_day["ISO Date"] = current_iso
            copied_day["Weekday"] = day_date.strftime("%A")

            st.session_state.schedule[selected_employee][current_iso] = copied_day

    st.success("Previous week copied.")
    st.rerun()


# -----------------------------
# Weekly Schedule Table
# -----------------------------

st.subheader("Weekly Schedule Table")

weekly_schedule_df = build_weekly_schedule_table(selected_week_dates)

st.dataframe(
    weekly_schedule_df,
    use_container_width=True,
    hide_index=True
)

weekly_coverage_df = build_weekly_assignment_coverage_table(selected_week_dates)

st.subheader("Weekly Assignment Coverage")

st.data_editor(
    weekly_coverage_df,
    use_container_width=True,
    hide_index=True,
    disabled=["Day", "Date", "Main", "2", "ER", "All Covered"],
    column_config={
        "Main": st.column_config.NumberColumn(
            "Main",
            help="Count of scheduled employees assigned to Main.",
            min_value=0,
            step=1
        ),
        "2": st.column_config.NumberColumn(
            "Room 2",
            help="Count of scheduled employees assigned to 2.",
            min_value=0,
            step=1
        ),
        "ER": st.column_config.NumberColumn(
            "ER",
            help="Count of scheduled employees assigned to ER.",
            min_value=0,
            step=1
        ),
        "All Covered": st.column_config.CheckboxColumn(
            "All Covered",
            help="Weekdays require 2, ER, and Main. Weekends require ER and Main."
        )
    },
    key="weekly_assignment_coverage_table"
)


# -----------------------------
# Monthly Schedule Table
# -----------------------------

st.subheader("Monthly Schedule Table")

for week_index, week_dates in enumerate(week_ranges, start=1):
    st.markdown(f"**Week {week_index}**")

    monthly_week_df = build_weekly_schedule_table(week_dates)
    st.dataframe(
        monthly_week_df,
        use_container_width=True,
        hide_index=True
    )

monthly_df = build_monthly_schedule_table(selected_year, selected_month)
csv = monthly_df.to_csv(index=False).encode("utf-8")

st.download_button(
    label="⬇️ Download Monthly Schedule as CSV",
    data=csv,
    file_name=f"employee_schedule_{selected_year}_{selected_month}.csv",
    mime="text/csv",
    use_container_width=True
)