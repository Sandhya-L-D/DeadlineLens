import importlib.util
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta, date
from typing import Any
from io import BytesIO
from pathlib import Path
import re
import html
import json
import pandas as pd
import plotly.express as px
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from services.auto_reminder_service import ( check_and_send_reminders,)
from services.email_service import send_deadline_email
import streamlit as st
from streamlit_calendar import calendar
from utils.activity_logger import (
    log_activity,
    get_activity_log,
)

from PIL import Image
from services.calendar_service import create_multiple_calendar_events
from database.database import (
    add_deadline,
    delete_deadline,
    get_all_deadlines,
    get_reminder_history,
    mark_reminder_as_sent,
    update_deadline_status,
    replace_study_plan,
    get_study_tasks,
    update_study_task_completion,
    delete_study_plan,
    rebalance_study_plan,
    add_study_session,
    get_study_sessions,
    delete_study_session,
    set_study_goal,
    get_study_goal,
    export_database_snapshot,
    get_database_file_bytes,
    inspect_database_backup,
    restore_database_backup,
    add_exam_resource,
    get_exam_resources,
    delete_exam_resource,
    add_mock_test,
    get_mock_tests,
    delete_mock_test,
)

from services.deadline_parser import extract_deadline, generate_title
from services.ocr_service import (
    extract_text,
    extract_timetable_rows,
)
from services.risk_calculator import calculate_risk, risk_label
from services.timetable_parser import (
    extract_exam_events,
    extract_exam_events_from_rows,
    filter_events_by_program,
    is_timetable,
)

def filter_events_by_program(
    events: list[dict],
    program: str,
) -> list[dict]:
    """Filter examination events by program."""

    selected_program = program.strip().upper()

    if selected_program == "ALL":
        return events

    filtered_events = []

    for event in events:
        course_code = str(
            event.get("subject", "")
        ).upper()

        if selected_program == "MCA":
            if "CA" in course_code:
                filtered_events.append(event)

        elif selected_program == "MBA":
            if "BA" in course_code and "CA" not in course_code:
                filtered_events.append(event)

    return filtered_events

st.set_page_config(
    page_title="DeadlineLens",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)
log_activity("Application started")

def load_css() -> None:
    """Load the DeadlineLens visual theme when available."""
    css_path = Path(__file__).resolve().parent / "assets" / "style.css"
    if css_path.exists():
        st.markdown(
            f"<style>{css_path.read_text(encoding='utf-8')}</style>",
            unsafe_allow_html=True,
        )


load_css()


SETTINGS_PATH = Path(__file__).resolve().parent / "database" / "app_settings.json"
DEFAULT_APP_SETTINGS = {
    "student_name": "",
    "default_program": "MCA",
    "default_study_hours": 2.0,
    "daily_goal_minutes": 120,
    "reminder_days_before": 2,
    "show_welcome_name": True,
}


def load_app_settings() -> dict[str, Any]:
    """Load user preferences without interrupting the application."""
    settings = DEFAULT_APP_SETTINGS.copy()
    try:
        if SETTINGS_PATH.exists():
            stored = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                settings.update(stored)
    except (OSError, json.JSONDecodeError):
        pass
    return settings


def save_app_settings(settings: dict[str, Any]) -> None:
    """Persist user preferences as a small portable JSON file."""
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def navigate_to(page_name: str) -> None:
    """Request a sidebar-page change from dashboard quick actions."""
    st.session_state["requested_nav_page"] = page_name
    st.rerun()


def show_app_footer() -> None:
    st.markdown(
        """
        <div class="dl-footer">
            <strong>DeadlineLens v2.0</strong><br>
            AI-Powered Academic Deadline Manager · © 2026
        </div>
        """,
        unsafe_allow_html=True,
    )



def format_countdown(deadline_datetime: datetime, now: datetime | None = None) -> tuple[str, str]:
    """Return a readable countdown label and state."""
    current_time = now or datetime.now()
    remaining = deadline_datetime - current_time
    seconds = int(remaining.total_seconds())

    if seconds < 0:
        overdue_seconds = abs(seconds)
        days, remainder = divmod(overdue_seconds, 86400)
        hours = remainder // 3600
        if days:
            return f"Overdue by {days} day(s)", "overdue"
        return f"Overdue by {hours} hour(s)", "overdue"

    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60

    if days > 0:
        return f"{days} day(s), {hours} hour(s) remaining", "upcoming"
    if hours > 0:
        return f"{hours} hour(s), {minutes} minute(s) remaining", "today"
    return f"{max(minutes, 0)} minute(s) remaining", "today"


def show_upcoming_countdowns(deadlines: list[dict[str, Any]], limit: int = 5) -> None:
    """Show compact countdown cards for the nearest pending deadlines."""
    now = datetime.now()
    pending_items: list[dict[str, Any]] = []

    for deadline in deadlines:
        if deadline.get("status") == "Completed":
            continue

        try:
            deadline_datetime = datetime.fromisoformat(deadline["deadline"])
        except (KeyError, TypeError, ValueError):
            continue

        pending_items.append({**deadline, "deadline_datetime": deadline_datetime})

    pending_items.sort(key=lambda item: item["deadline_datetime"])

    if not pending_items:
        st.success("No pending deadlines. You are all caught up!")
        return

    st.subheader("⏳ Upcoming Countdown")

    for item in pending_items[:limit]:
        deadline_datetime = item["deadline_datetime"]
        countdown_text, state = format_countdown(deadline_datetime, now)

        with st.container(border=True):
            title_column, countdown_column = st.columns([3, 2])

            with title_column:
                st.markdown(f"**{item['title']}**")
                st.caption(
                    f"{item.get('subject') or 'No subject'} • "
                    f"{deadline_datetime.strftime('%d %b %Y, %I:%M %p')}"
                )

            with countdown_column:
                if state == "overdue":
                    st.error(countdown_text)
                elif state == "today":
                    st.warning(countdown_text)
                else:
                    st.info(countdown_text)


def show_notification_center(deadlines: list[dict[str, Any]], limit: int = 8) -> None:
    """Display actionable deadline notifications grouped by urgency."""
    now = datetime.now()
    notifications: list[dict[str, Any]] = []

    for deadline in deadlines:
        if deadline.get("status") == "Completed":
            continue

        try:
            deadline_datetime = datetime.fromisoformat(deadline["deadline"])
        except (KeyError, TypeError, ValueError):
            continue

        difference = deadline_datetime - now
        total_seconds = difference.total_seconds()
        calendar_days = (deadline_datetime.date() - now.date()).days

        if total_seconds < 0:
            category = "overdue"
            priority = 0
            elapsed = now - deadline_datetime
            if elapsed.days >= 1:
                message = f"Overdue by {elapsed.days} day(s)"
            else:
                hours = max(int(elapsed.total_seconds() // 3600), 1)
                message = f"Overdue by {hours} hour(s)"
        elif calendar_days == 0:
            category = "today"
            priority = 1
            message = f"Due today at {deadline_datetime.strftime('%I:%M %p')}"
        elif calendar_days == 1:
            category = "tomorrow"
            priority = 2
            message = f"Due tomorrow at {deadline_datetime.strftime('%I:%M %p')}"
        elif calendar_days <= 3:
            category = "soon"
            priority = 3
            message = f"Due in {calendar_days} days"
        elif calendar_days <= 7:
            category = "week"
            priority = 4
            message = f"Due this week — {deadline_datetime.strftime('%A')}"
        else:
            continue

        notifications.append(
            {
                **deadline,
                "deadline_datetime": deadline_datetime,
                "category": category,
                "priority": priority,
                "message": message,
            }
        )

    notifications.sort(
        key=lambda item: (
            item["priority"],
            item["deadline_datetime"],
        )
    )

    st.subheader("🔔 Smart Notification Center")

    if not notifications:
        st.success("No urgent notifications for the next seven days.")
        return

    for item in notifications[:limit]:
        category = item["category"]
        labels = {
            "overdue": "🔴 OVERDUE",
            "today": "🟠 TODAY",
            "tomorrow": "🟡 TOMORROW",
            "soon": "🟣 COMING SOON",
            "week": "🔵 THIS WEEK",
        }

        with st.container(border=True):
            heading_column, status_column = st.columns([3, 2])

            with heading_column:
                st.markdown(f"**{labels[category]} — {item['title']}**")
                st.caption(
                    f"{item.get('subject') or 'No subject'} • "
                    f"{item['deadline_datetime'].strftime('%d %b %Y, %I:%M %p')}"
                )

            with status_column:
                if category == "overdue":
                    st.error(item["message"])
                elif category in {"today", "tomorrow"}:
                    st.warning(item["message"])
                else:
                    st.info(item["message"])

    remaining_count = len(notifications) - limit
    if remaining_count > 0:
        st.caption(f"And {remaining_count} more urgent notification(s).")


def save_single_deadline(
    title: str,
    subject: str,
    extracted_text: str,
    final_deadline: datetime,
    difficulty: str,
    risk_score: int,
) -> None:
    saved = add_deadline(
        title=title.strip(),
        subject=subject.strip(),
        description=extracted_text[:500],
        deadline=final_deadline.isoformat(),
        difficulty=difficulty,
        risk_score=risk_score,
        source_text=extracted_text,
    )

    if saved:
        st.success("Deadline saved successfully!")
    else:
        st.warning(
            "This deadline already exists in the database."
        )


def show_single_deadline_form(
    extracted_text: str,
    detected_title: str,
    detected_deadline: datetime | None,
) -> None:
    st.subheader("📝 Detected Deadline")

    title = st.text_input(
        "Task title",
        value=detected_title,
    )

    subject = st.text_input("Subject")

    difficulty = st.selectbox(
        "Difficulty",
        ["Low", "Medium", "High"],
        index=1,
    )

    if detected_deadline:
        default_date = detected_deadline.date()
        default_time = detected_deadline.time()
    else:
        default_date = datetime.now().date()
        default_time = datetime.now().replace(
            hour=9,
            minute=0,
            second=0,
            microsecond=0,
        ).time()

        st.warning(
            "No deadline was detected. "
            "Please enter the date and time manually."
        )

    date_column, time_column = st.columns(2)

    with date_column:
        deadline_date = st.date_input(
            "Deadline date",
            value=default_date,
        )

    with time_column:
        deadline_time = st.time_input(
            "Deadline time",
            value=default_time,
        )

    final_deadline = datetime.combine(
        deadline_date,
        deadline_time,
    )

    risk_score = calculate_risk(
        deadline=final_deadline,
        difficulty=difficulty,
        pending_tasks=3,
        status="Not Started",
    )

    st.metric(
        "Deadline risk",
        f"{risk_score}%",
        risk_label(risk_score),
    )

    if st.button(
        "Save deadline",
        type="primary",
        key="save_single_deadline",
    ):
        if not title.strip():
            st.error("Please enter a task title.")
            return

        save_single_deadline(
            title=title,
            subject=subject,
            extracted_text=extracted_text,
            final_deadline=final_deadline,
            difficulty=difficulty,
            risk_score=risk_score,
        )
def show_timetable_form(
    extracted_text: str,
    timetable_rows: list[str],
) -> None:
    st.info(
        "Examination timetable detected. "
        "DeadlineLens will search for multiple exam events."
    )

    st.subheader("🧠 Detected Examination Events")

    row_events = extract_exam_events_from_rows(
        timetable_rows
)

    # Use text parsing only as a fallback.
    if row_events:
        all_exam_events = row_events
    else:
        all_exam_events = extract_exam_events(
        extracted_text
    )

    all_exam_events = sorted(
        all_exam_events,
        key=lambda event: (
            event["deadline"],
            event["subject"],
    ),
)
    st.write("Total parsed events:", len(all_exam_events))

    st.dataframe(
    [
        {
            "course_code": event["subject"],
            "date": event["deadline"].strftime("%d-%m-%Y"),
            "source": event["description"],
        }
        for event in all_exam_events
    ],
    width="stretch"
)

    program_options = ["MCA", "MBA", "All"]
    preferred_program = str(
        load_app_settings().get("default_program", "MCA")
    ).upper()
    preferred_index = (
        program_options.index(preferred_program)
        if preferred_program in program_options
        else 0
    )
    program = st.selectbox(
        "Choose your program",
        program_options,
        index=preferred_index,
        key="timetable_program",
    )

    exam_events = filter_events_by_program(
        all_exam_events,
        program,
    )

    if not exam_events:
        st.warning(
            "The document looks like a timetable, but no exam rows "
            "were detected. OCR may not have preserved the table text."
        )
        return

    st.success(
        f"{len(exam_events)} {program} examination event(s) detected."
    )

    select_all = st.checkbox(
        "Select all displayed examinations",
        value=True,
        key=f"select_all_{program}",
    )

    selected_events: list[dict[str, Any]] = []

    for index, event in enumerate(exam_events):
        with st.container(border=True):
            selected = st.checkbox(
                "Include this exam",
                value=select_all,
                key=f"include_exam_{program}_{index}",
            )

            event_title = st.text_input(
                "Event title",
                value=event["title"],
                key=f"exam_title_{program}_{index}",
            )

            event_subject = st.text_input(
                "Course code",
                value=event["subject"],
                key=f"exam_subject_{program}_{index}",
            )

            date_column, time_column = st.columns(2)

            with date_column:
                event_date = st.date_input(
                    "Exam date",
                    value=event["deadline"].date(),
                    key=f"exam_date_{program}_{index}",
                )

            with time_column:
                event_time = st.time_input(
                    "Exam time",
                    value=event["deadline"].time(),
                    key=f"exam_time_{program}_{index}",
                )

            if selected:
                selected_events.append(
                    {
                        "title": event_title.strip(),
                        "subject": event_subject.strip(),
                        "deadline": datetime.combine(
                            event_date,
                            event_time,
                        ),
                        "description": event["description"],
                    }
                )

    save_column, calendar_column = st.columns(2)

    with save_column:
        save_clicked = st.button(
            "Save selected examinations",
            type="primary",
            key="save_exam_events",
            width="stretch",
        )

    with calendar_column:
        calendar_clicked = st.button(
            "📅 Add selected exams to Google Calendar",
            key="add_selected_exams_to_calendar",
            width="stretch",
        )

    if save_clicked:
        if not selected_events:
            st.warning(
                "Please select at least one examination."
            )
            return

        saved_count = 0
        duplicate_count = 0
        failed_events: list[str] = []

        with st.spinner("Saving selected examinations..."):
            for event in selected_events:
                try:
                    event_risk = calculate_risk(
                        deadline=event["deadline"],
                        difficulty="High",
                        pending_tasks=len(selected_events),
                        status="Not Started",
                    )

                    saved = add_deadline(
                        title=event["title"],
                        subject=event["subject"],
                        description=event["description"],
                        deadline=event["deadline"].isoformat(),
                        difficulty="High",
                        risk_score=event_risk,
                        source_text=extracted_text,
                    )

                    if saved:
                        saved_count += 1
                    else:
                        duplicate_count += 1

                except Exception:
                    failed_events.append(
                        event["title"]
                    )

        if saved_count:
            st.success(
                f"{saved_count} examination event(s) "
                "saved successfully."
            )

        if duplicate_count:
            st.warning(
                f"{duplicate_count} duplicate event(s) "
                "were skipped."
            )

        if failed_events:
            st.error(
                "Failed to save: "
                + ", ".join(failed_events)
            )

        if saved_count:
            st.rerun()

    if calendar_clicked:
        if not selected_events:
            st.warning(
                "Please select at least one examination."
            )
            return

        try:
            with st.spinner(
                "Adding exams to Google Calendar..."
            ):
                success_count, failed_events = (
                    create_multiple_calendar_events(
                        selected_events
                    )
                )

            if success_count:
                st.success(
                    f"{success_count} exam event(s) "
                    "added to Google Calendar successfully."
                )

            if failed_events:
                st.error(
                    "These events could not be added: "
                    + ", ".join(failed_events)
                )

        except Exception as error:
            st.error(
                "Google Calendar integration failed."
            )
            st.exception(error)
def show_analytics_charts() -> None:
    """Display visual analytics for saved deadlines."""

    deadlines = get_all_deadlines()

    if not deadlines:
        return

    st.header("📈 Deadline Analytics")

    status_data = {
        "Status": [
            "Completed",
            "Pending",
        ],
        "Count": [
            sum(
                1
                for deadline in deadlines
                if deadline["status"] == "Completed"
            ),
            sum(
                1
                for deadline in deadlines
                if deadline["status"] != "Completed"
            ),
        ],
    }

    risk_labels = []

    for deadline in deadlines:
        score = deadline["risk_score"]

        if score >= 80:
            risk_labels.append("Critical")
        elif score >= 60:
            risk_labels.append("High")
        elif score >= 35:
            risk_labels.append("Moderate")
        else:
            risk_labels.append("Low")

    risk_data = {
        "Risk Level": [
            "Critical",
            "High",
            "Moderate",
            "Low",
        ],
        "Count": [
            risk_labels.count("Critical"),
            risk_labels.count("High"),
            risk_labels.count("Moderate"),
            risk_labels.count("Low"),
        ],
    }

    difficulty_levels = [
        deadline["difficulty"]
        for deadline in deadlines
    ]

    difficulty_data = {
        "Difficulty": [
            "High",
            "Medium",
            "Low",
        ],
        "Count": [
            difficulty_levels.count("High"),
            difficulty_levels.count("Medium"),
            difficulty_levels.count("Low"),
        ],
    }

    left_chart, right_chart = st.columns(2)

    with left_chart:
        status_figure = px.pie(
            status_data,
            names="Status",
            values="Count",
            title="Completion Status",
            hole=0.45,
        )

        st.plotly_chart(
            status_figure,
            width="stretch",
        )

    with right_chart:
        risk_figure = px.bar(
            risk_data,
            x="Risk Level",
            y="Count",
            title="Risk Distribution",
        )

        st.plotly_chart(
            risk_figure,
            width="stretch",
        )

    difficulty_figure = px.bar(
        difficulty_data,
        x="Difficulty",
        y="Count",
        title="Deadlines by Difficulty",
    )

    st.plotly_chart(
        difficulty_figure,
        width="stretch",
    )  
def show_reminder_center() -> None:
    """Display automatic reminders for upcoming deadlines."""

    deadlines = get_all_deadlines()

    if not deadlines:
        return

    now = datetime.now()

    upcoming_items = []

    for deadline in deadlines:
        if deadline["status"] == "Completed":
            continue

        deadline_datetime = datetime.fromisoformat(
            deadline["deadline"]
        )

        time_remaining = deadline_datetime - now
        total_seconds = time_remaining.total_seconds()

        if total_seconds < 0:
            reminder_level = "Overdue"
            priority = 0

        else:
            days_remaining = time_remaining.days

            if days_remaining == 0:
                reminder_level = "Today"
                priority = 1

            elif days_remaining == 1:
                reminder_level = "Tomorrow"
                priority = 2

            elif days_remaining <= 3:
                reminder_level = "Within 3 days"
                priority = 3

            elif days_remaining <= 7:
                reminder_level = "Within 7 days"
                priority = 4

            else:
                continue

        upcoming_items.append(
            {
                **deadline,
                "deadline_datetime": deadline_datetime,
                "reminder_level": reminder_level,
                "priority": priority,
            }
        )

    if not upcoming_items:
        return

    upcoming_items.sort(
        key=lambda item: (
            item["priority"],
            item["deadline_datetime"],
        )
    )

    st.header("🔔 Smart Reminder Center")

    st.caption(
        f"You have {len(upcoming_items)} important "
        "deadline reminder(s)."
    )

    for item in upcoming_items:
        deadline_datetime = item["deadline_datetime"]
        reminder_level = item["reminder_level"]

        with st.container(border=True):
            left, right = st.columns([4, 1])

            with left:
                st.subheader(item["title"])

                st.write(
                    f"**Subject:** "
                    f"{item['subject'] or 'Not specified'}"
                )

                st.write(
                    "**Date:** "
                    f"{deadline_datetime.strftime('%d %B %Y')}"
                )

                st.write(
                    "**Time:** "
                    f"{deadline_datetime.strftime('%I:%M %p')}"
                )

                st.write(
                    f"**Risk score:** "
                    f"{item['risk_score']}%"
                )

            with right:
                if reminder_level == "Overdue":
                    st.error("Overdue")

                elif reminder_level == "Today":
                    st.error("Today")

                elif reminder_level == "Tomorrow":
                    st.warning("Tomorrow")

                elif reminder_level == "Within 3 days":
                    st.warning("Within 3 days")

                else:
                    st.info("Within 7 days") 
def show_email_reminder_test() -> None:
    """Display controls for sending single or bulk reminder emails."""

    st.header("📧 Email Reminder")

    deadlines = get_all_deadlines()

    if not deadlines:
        st.info(
            "Save at least one deadline before sending reminders."
        )
        return

    pending_deadlines = [
        deadline
        for deadline in deadlines
        if deadline["status"] != "Completed"
    ]

    if not pending_deadlines:
        st.success(
            "There are no pending deadlines requiring reminders."
        )
        return

    recipient_email = st.text_input(
    "Recipient Email Address",
    placeholder="yourname@gmail.com",
    key="reminder_email",
        )

    deadline_options = {
        (
            f"{deadline['title']} — "
            f"{datetime.fromisoformat(deadline['deadline']).strftime('%d %B %Y')}"
        ): deadline
        for deadline in pending_deadlines
    }

    selected_label = st.selectbox(
        "Choose deadline",
        list(deadline_options.keys()),
        key="email_deadline_selection",
    )

    selected_deadline = deadline_options[selected_label]

    selected_deadline_datetime = datetime.fromisoformat(
        selected_deadline["deadline"]
    )

    single_column, bulk_column = st.columns(2)

    with single_column:
        send_single = st.button(
            "Send selected reminder",
            key="send_test_reminder_email",
            width="stretch",
        )

    with bulk_column:
        send_all = st.button(
            "Send all pending reminders",
            key="send_all_reminders",
           width="stretch",
        )

    if send_single:
        if not recipient_email.strip():
            st.error("Please enter your email address.")
            return

        try:
            with st.spinner("Sending reminder email..."):
                send_deadline_email(
                    recipient=recipient_email.strip(),
                    title=selected_deadline["title"],
                    subject=selected_deadline["subject"],
                    deadline_text=selected_deadline_datetime.strftime(
                        "%d %B %Y, %I:%M %p"
                    ),
                    risk_score=selected_deadline["risk_score"],
                )
            mark_reminder_as_sent(
            deadline_id=selected_deadline["id"],
            recipient_email=recipient_email.strip().lower(),
            reminder_type="manual_selected",
                )
            st.toast(
                 "Reminder email sent successfully!",
                  icon="📧",
                 )

        except Exception as error:
            st.error(
                "The reminder email could not be sent."
            )
            st.exception(error)

    if send_all:
        if not recipient_email.strip():
            st.error("Please enter your email address.")
            return

        sent_count = 0
        failed_titles = []

        with st.spinner(
            "Sending reminder emails..."
        ):
            for deadline in pending_deadlines:
                deadline_datetime = datetime.fromisoformat(
                    deadline["deadline"]
                )

                try:
                    send_deadline_email(
                        recipient=recipient_email.strip(),
                        title=deadline["title"],
                        subject=deadline["subject"],
                        deadline_text=deadline_datetime.strftime(
                            "%d %B %Y, %I:%M %p"
                        ),
                        risk_score=deadline["risk_score"],
                    )
                    mark_reminder_as_sent(
                         deadline_id=deadline["id"],
                         recipient_email=recipient_email.strip().lower(),
                          reminder_type="manual_all_pending",
                           )

                    sent_count += 1
                except Exception:
                    failed_titles.append(
                        deadline["title"]
                    )

        if sent_count:
            st.toast(
                f"{sent_count} reminder email(s) sent successfully!",
                 icon="📧",
                    )

        if failed_titles:
            st.error(
                "Failed to send reminders for: "
                + ", ".join(failed_titles)
            )                                
def show_dashboard() -> None:
    """Display deadline statistics and upcoming exam information."""

    hour = datetime.now().hour
    greeting = (
        "Good morning" if hour < 12
        else "Good afternoon" if hour < 17
        else "Good evening"
    )

    app_settings = load_app_settings()
    student_name = str(app_settings.get("student_name", "")).strip()
    show_name = bool(app_settings.get("show_welcome_name", True))
    greeting_name = f", {html.escape(student_name)}" if student_name and show_name else ""

    st.markdown(
        f"""
        <div class="dl-hero">
            <h1>🎓 {greeting}{greeting_name}!</h1>
            <p>Stay ahead of exams, deadlines, reminders, and study goals from one focused workspace.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="dl-section-title">⚡ Quick Actions</div>', unsafe_allow_html=True)
    action_one, action_two, action_three, action_four = st.columns(4)
    if action_one.button("📄 Upload Notice", width="stretch", key="quick_upload"):
        navigate_to("Upload Notice")
    if action_two.button("📚 Study Planner", width="stretch", key="quick_planner"):
        navigate_to("Study Planner")
    if action_three.button("📅 Calendar", width="stretch", key="quick_calendar"):
        navigate_to("Calendar")
    if action_four.button("📊 Analytics", width="stretch", key="quick_analytics"):
        navigate_to("Analytics")

    deadlines = get_all_deadlines()

    if not deadlines:
        st.info(
            "🎉 You are all caught up! Upload a notice to create your first academic deadline."
        )
        return

    now = datetime.now()

    total_deadlines = len(deadlines)

    completed_deadlines = sum(
        1
        for deadline in deadlines
        if deadline["status"] == "Completed"
    )

    pending_deadlines = sum(
        1
        for deadline in deadlines
        if deadline["status"] != "Completed"
    )

    high_risk_deadlines = sum(
        1
        for deadline in deadlines
        if deadline["risk_score"] >= 60
        and deadline["status"] != "Completed"
    )

    first, second, third, fourth = st.columns(4)

    with first:
        st.metric(
            "Total Deadlines",
            total_deadlines,
        )

    with second:
        st.metric(
            "Pending",
            pending_deadlines,
        )

    with third:
        st.metric(
            "Completed",
            completed_deadlines,
        )

    with fourth:
        st.metric(
            "High Risk",
            high_risk_deadlines,
        )

    completion_percentage = (
        completed_deadlines / total_deadlines
    ) * 100

    st.subheader("Overall progress")

    st.progress(
        int(completion_percentage)
    )

    st.caption(
        f"{completion_percentage:.0f}% of your deadlines "
        "have been completed."
    )

    show_notification_center(deadlines)

    show_upcoming_countdowns(deadlines)

    upcoming_deadlines = []

    for deadline in deadlines:
        deadline_datetime = datetime.fromisoformat(
            deadline["deadline"]
        )

        if (
            deadline_datetime >= now
            and deadline["status"] != "Completed"
        ):
            upcoming_deadlines.append(
                {
                    **deadline,
                    "deadline_datetime": deadline_datetime,
                }
            )

    upcoming_deadlines.sort(
        key=lambda item: item["deadline_datetime"]
    )

    st.subheader("⏳ Next Upcoming Deadline")

    if upcoming_deadlines:
        next_deadline = upcoming_deadlines[0]
        next_datetime = next_deadline[
            "deadline_datetime"
        ]

        remaining_time = next_datetime - now
        days_remaining = remaining_time.days

        with st.container(border=True):
            st.subheader(
                next_deadline["title"]
            )

            st.write(
                f"**Subject:** "
                f"{next_deadline['subject'] or 'Not specified'}"
            )

            st.write(
                "**Date:** "
                f"{next_datetime.strftime('%d %B %Y')}"
            )

            st.write(
                "**Time:** "
                f"{next_datetime.strftime('%I:%M %p')}"
            )

            if days_remaining > 1:
                st.info(
                    f"{days_remaining} days remaining."
                )

            elif days_remaining == 1:
                st.warning(
                    "Only 1 day remaining."
                )

            else:
                st.error(
                    "This deadline is today."
                )

    else:
        st.success(
            "There are no pending upcoming deadlines."
        )

    st.subheader("📥 Export Deadline Data")

    export_rows = []

    for deadline in deadlines:
        deadline_datetime = datetime.fromisoformat(
            deadline["deadline"]
        )

        export_rows.append(
            {
                "Title": deadline["title"],
                "Subject": (
                    deadline["subject"]
                    or "Not specified"
                ),
                "Deadline Date": (
                    deadline_datetime.strftime(
                        "%d-%m-%Y"
                    )
                ),
                "Deadline Time": (
                    deadline_datetime.strftime(
                        "%I:%M %p"
                    )
                ),
                "Difficulty": deadline["difficulty"],
                "Status": deadline["status"],
                "Risk Score": deadline["risk_score"],
            }
        )

    dataframe = pd.DataFrame(export_rows)

    csv_data = dataframe.to_csv(
        index=False
    ).encode("utf-8")

    st.download_button(
        label="Download deadlines as CSV",
        data=csv_data,
        file_name="deadlinelens_deadlines.csv",
        mime="text/csv",
    )
def show_system_health() -> None:
    st.title("🩺 System Health")

    database_ok = False
    database_size = "Unknown"

    try:
        db_path = Path("database/deadlines.db")

        if db_path.exists():
            sqlite3.connect(db_path).close()
            database_ok = True
            database_size = (
                f"{db_path.stat().st_size / (1024 * 1024):.2f} MB"
            )

    except sqlite3.Error:
        database_ok = False

    ocr_ok = (
        importlib.util.find_spec("easyocr")
        is not None
    )

    calendar_ok = Path(
        "google_token.json"
    ).exists()

    email_ok = Path(
        "credentials.json"
    ).exists()

    activity_log_ok = Path(
        "database/activity_log.json"
    ).exists()

    try:
        deadline_count = len(
            get_all_deadlines()
        )
    except Exception:
        deadline_count = 0

    backup_folder = Path("backups")

    backup_ok = (
        backup_folder.exists()
        and any(backup_folder.iterdir())
    )

    st.subheader("Component Status")

    column_1, column_2 = st.columns(2)

    with column_1:
        st.metric(
            "🗄 Database",
            "Connected" if database_ok else "Error",
        )

        st.metric(
            "📦 Database Size",
            database_size,
        )

    with column_2:
        st.metric(
            "🔍 OCR",
            "Ready" if ocr_ok else "Missing",
        )

        st.metric(
            "📅 Google Calendar",
            (
                "Configured"
                if calendar_ok
                else "Not Configured"
            ),
        )

        st.metric(
            "📧 Email",
            (
                "Configured"
                if email_ok
                else "Not Configured"
            ),
        )

    st.subheader("Application Statistics")

    stat_1, stat_2, stat_3 = st.columns(3)

    with stat_1:
        st.metric(
            "📄 Saved Deadlines",
            deadline_count,
        )

    with stat_2:
        st.metric(
            "📜 Activity Logger",
            (
                "Working"
                if activity_log_ok
                else "No Log Yet"
            ),
        )

    with stat_3:
        st.metric(
            "💾 Backup Status",
            (
                "Available"
                if backup_ok
                else "No Backup Found"
            ),
        )

    st.subheader("Diagnostics")

    if st.button(
        "🔍 Run Full Diagnostics",
        use_container_width=True,
        key="run_full_diagnostics",
    ):
        checks = {
            "Database": database_ok,
            "OCR Engine": ocr_ok,
            "Google Calendar": calendar_ok,
            "Email Configuration": email_ok,
            "Activity Logger": activity_log_ok,
        }

        for component, status in checks.items():
            if status:
                st.success(
                    f"✅ {component}: Working"
                )
            else:
                st.warning(
                    f"⚠️ {component}: Needs attention"
                )

        if all(checks.values()):
            st.success(
                "🎉 All core components are healthy."
            )
        else:
            st.warning(
                "Some components need attention."
            )
def show_saved_deadlines() -> None:
    st.divider()
    st.header("📅 Saved Deadlines")

    saved_deadlines = get_all_deadlines()

    if not saved_deadlines:
        st.info("No deadlines have been saved yet.")
        return

    search_column, filter_column, sort_column = st.columns(
        [2, 1, 1]
    )

    with search_column:
        search_text = st.text_input(
            "Search deadlines",
            placeholder="Search by title or subject...",
            key="deadline_search",
        )

    with filter_column:
        status_filter = st.selectbox(
            "Filter by status",
            [
                "All",
                "Not Started",
                "In Progress",
                "Completed",
                "High Risk",
            ],
            key="deadline_status_filter",
        )

    with sort_column:
        sort_option = st.selectbox(
            "Sort by",
            [
                "Nearest deadline",
                "Latest deadline",
                "Highest risk",
                "Lowest risk",
                "Title A-Z",
            ],
            key="deadline_sort",
        )

    filtered_deadlines = []
    search_query = search_text.strip().lower()

    for deadline in saved_deadlines:
        title = str(deadline["title"]).lower()
        subject = str(
            deadline["subject"] or ""
        ).lower()

        matches_search = (
            not search_query
            or search_query in title
            or search_query in subject
        )

        if not matches_search:
            continue

        if status_filter == "All":
            matches_filter = True

        elif status_filter == "High Risk":
            matches_filter = (
                deadline["risk_score"] >= 60
                and deadline["status"] != "Completed"
            )

        else:
            matches_filter = (
                deadline["status"] == status_filter
            )

        if matches_filter:
            filtered_deadlines.append(deadline)

    if sort_option == "Nearest deadline":
        filtered_deadlines.sort(
            key=lambda item: datetime.fromisoformat(
                item["deadline"]
            )
        )

    elif sort_option == "Latest deadline":
        filtered_deadlines.sort(
            key=lambda item: datetime.fromisoformat(
                item["deadline"]
            ),
            reverse=True,
        )

    elif sort_option == "Highest risk":
        filtered_deadlines.sort(
            key=lambda item: item["risk_score"],
            reverse=True,
        )

    elif sort_option == "Lowest risk":
        filtered_deadlines.sort(
            key=lambda item: item["risk_score"]
        )

    elif sort_option == "Title A-Z":
        filtered_deadlines.sort(
            key=lambda item: item["title"].lower()
        )

    st.caption(
        f"Showing {len(filtered_deadlines)} of "
        f"{len(saved_deadlines)} deadline(s)."
    )

    if not filtered_deadlines:
        st.warning(
            "No deadlines match your search or filter."
        )
        return

    for deadline in filtered_deadlines:
        deadline_datetime = datetime.fromisoformat(
            deadline["deadline"]
        )

        with st.container(border=True):
            left, middle, right = st.columns([3, 2, 1])

            with left:
                st.subheader(deadline["title"])

                subject_value = (
                    deadline["subject"]
                    or "Not specified"
                )

                st.write(
                    f"**Subject:** {subject_value}"
                )

                st.write(
                    "**Deadline:** "
                    f"{deadline_datetime.strftime('%d %B %Y, %I:%M %p')}"
                )

                st.write(
                    f"**Difficulty:** "
                    f"{deadline['difficulty']}"
                )

                st.write(
                    f"**Risk score:** "
                    f"{deadline['risk_score']}%"
                )

                if deadline["risk_score"] >= 80:
                    st.error("Critical risk")

                elif deadline["risk_score"] >= 60:
                    st.warning("High risk")

                elif deadline["risk_score"] >= 35:
                    st.info("Moderate risk")

                else:
                    st.success("Low risk")

            with middle:
                status_options = [
                    "Not Started",
                    "In Progress",
                    "Completed",
                ]

                current_status = deadline["status"]

                if current_status not in status_options:
                    current_status = "Not Started"

                selected_status = st.selectbox(
                    "Status",
                    status_options,
                    index=status_options.index(
                        current_status
                    ),
                    key=f"status_{deadline['id']}",
                )

                if selected_status != current_status:
                    update_deadline_status(
                        deadline["id"],
                        selected_status,
                    )

                    st.success("Status updated.")
                    st.rerun()
            with right:
                st.write("")
                st.write("")

                delete_key = f"confirm_delete_{deadline['id']}"

                if delete_key not in st.session_state:
                    st.session_state[delete_key] = False

                # First stage: show only the Delete button
                if not st.session_state[delete_key]:
                    if st.button(
                        "Delete",
                        key=f"delete_button_{deadline['id']}",
                ):
                        st.session_state[delete_key] = True
                        st.rerun()

                # Second stage: show confirmation buttons
                else:
                   st.warning(
                       f"Delete '{deadline['title']}' permanently?"
                   )

                   confirm_column, cancel_column = st.columns(2)

                   with confirm_column:
                      if st.button(
                          "Yes, delete",
                          type="primary",
                          key=f"confirm_delete_button_{deadline['id']}",
                      ):
                          delete_deadline(deadline["id"])

                          st.session_state.pop(
                              delete_key,
                              None,
                          )

                          st.rerun()

                   with cancel_column:
                      if st.button(
                          "Cancel",
                           key=f"cancel_delete_button_{deadline['id']}",
                      ):
                           st.session_state[delete_key] = False
                           st.rerun()        

           
def show_upload_page() -> None:
    """Upload and process a notice or examination timetable image."""

    uploaded_file = st.file_uploader(
        "Upload a notice screenshot",
        type=["jpg", "jpeg", "png"],
    )

    if uploaded_file:
        try:
            image = Image.open(uploaded_file)

            left_column, right_column = st.columns(2)

            with left_column:
                st.subheader("Uploaded notice")
                st.image(
                    image,
                    width="stretch",
                )

            with right_column:
                st.subheader("Extracted information")

                with st.spinner(
                    "Reading the notice..."
                ):
                    extracted_text = extract_text(image)

                    timetable_rows = extract_timetable_rows(image)

                    document_is_timetable = is_timetable(
                        extracted_text
                    )
                    detected_deadline = extract_deadline(
                        extracted_text
                    )
                    detected_title = generate_title(
                        extracted_text
                    )

                st.text_area(
                    "Extracted text",
                    extracted_text,
                    height=180,
                )

                if not extracted_text.strip():
                    st.error(
                        "No readable text was detected. "
                        "Try uploading a clearer image."
                    )

                elif document_is_timetable:
                          show_timetable_form(
                      extracted_text,
                      timetable_rows,
                    )
                else:
                    show_single_deadline_form(
                        extracted_text=extracted_text,
                        detected_title=detected_title,
                        detected_deadline=detected_deadline,
                    )

        except Exception as error:
            st.error(
                "Something went wrong while processing "
                "the uploaded image."
            )
            st.exception(error)


def show_calendar_page() -> None:
    """Display saved deadlines in an interactive calendar."""

    st.header("📅 Academic Calendar")
    deadlines = get_all_deadlines()

    if not deadlines:
        st.info("Save at least one deadline to view the calendar.")
        return

    calendar_events: list[dict[str, Any]] = []

    for deadline in deadlines:
        try:
            deadline_datetime = datetime.fromisoformat(deadline["deadline"])
        except (TypeError, ValueError, KeyError):
            continue

        subject = deadline.get("subject") or "General"
        status = deadline.get("status") or "Not Started"
        calendar_events.append({
            "title": f"{subject} — {deadline['title']}",
            "start": deadline_datetime.isoformat(),
            "allDay": False,
            "extendedProps": {
                "status": status,
                "difficulty": deadline.get("difficulty", "Medium"),
                "risk_score": deadline.get("risk_score", 0),
                "description": deadline.get("description", ""),
            },
        })

    if not calendar_events:
        st.warning("No valid deadline dates were available for the calendar.")
        return

    calendar_options = {
        "initialView": "dayGridMonth",
        "height": 680,
        "headerToolbar": {
            "left": "prev,next today",
            "center": "title",
            "right": "dayGridMonth,timeGridWeek,listMonth",
        },
        "buttonText": {
            "today": "Today",
            "month": "Month",
            "week": "Week",
            "list": "List",
        },
        "navLinks": True,
        "editable": False,
        "selectable": False,
    }

    result = calendar(
        events=calendar_events,
        options=calendar_options,
        key="academic_deadline_calendar",
    )

    clicked = result.get("eventClick") if result else None
    if clicked:
        event_data = clicked.get("event", {})
        properties = event_data.get("extendedProps", {})
        with st.container(border=True):
            st.subheader("Selected deadline")
            st.write(f"**Title:** {event_data.get('title', 'Unknown')}")
            st.write(f"**Date and time:** {event_data.get('start', 'Unknown')}")
            st.write(f"**Status:** {properties.get('status', 'Not Started')}")
            st.write(f"**Difficulty:** {properties.get('difficulty', 'Medium')}")
            st.write(f"**Risk score:** {properties.get('risk_score', 0)}%")
            description = properties.get("description", "")
            if description:
                st.write(f"**Description:** {description}")


def show_reminder_history() -> None:
    st.divider()
    st.header("📨 Reminder History")

    reminders = get_reminder_history()

    if not reminders:
        st.info("No reminder emails have been recorded yet.")
        return

    search_text = st.text_input(
        "Search reminder history",
        placeholder="Search by title, subject, or email...",
        key="reminder_history_search",
    )

    filtered_reminders = reminders

    if search_text.strip():
        query = search_text.strip().lower()

        filtered_reminders = [
            reminder
            for reminder in reminders
            if query in str(
                reminder.get("title") or ""
            ).lower()
            or query in str(
                reminder.get("subject") or ""
            ).lower()
            or query in str(
                reminder.get("recipient_email") or ""
            ).lower()
        ]

    st.caption(
        f"Showing {len(filtered_reminders)} "
        f"of {len(reminders)} reminder record(s)."
    )

    if not filtered_reminders:
        st.warning("No reminder history matched your search.")
        return

    for reminder in filtered_reminders:
        sent_at = datetime.fromisoformat(
            reminder["sent_at"]
        )

        deadline_text = reminder.get("deadline")

        if deadline_text:
            deadline_datetime = datetime.fromisoformat(
                deadline_text
            )

            formatted_deadline = deadline_datetime.strftime(
                "%d %B %Y, %I:%M %p"
            )
        else:
            formatted_deadline = "Deadline deleted"

        with st.container(border=True):
            left, right = st.columns([3, 2])

            with left:
                st.subheader(
                    reminder.get("title")
                    or "Deleted deadline"
                )

                st.write(
                    f"**Subject:** "
                    f"{reminder.get('subject') or 'Not specified'}"
                )

                st.write(
                    f"**Recipient:** "
                    f"{reminder['recipient_email']}"
                )

                st.write(
                    f"**Reminder type:** "
                    f"{reminder['reminder_type']}"
                )

            with right:
                st.write(
                    f"**Deadline:** {formatted_deadline}"
                )

                st.write(
                    "**Sent at:** "
                    f"{sent_at.strftime('%d %B %Y, %I:%M %p')}"
                )
def build_exam_study_schedule(
    exam: dict[str, Any],
    unit_count: int,
    daily_hours: float,
) -> list[dict[str, Any]]:
    """Generate a balanced day-by-day study plan up to the exam date."""
    today = datetime.now().date()

    try:
        exam_datetime = datetime.fromisoformat(exam["deadline"])
    except (KeyError, TypeError, ValueError):
        return []

    exam_date = exam_datetime.date()
    study_days = (exam_date - today).days

    if study_days <= 0:
        return []

    available_dates = [
        today + timedelta(days=offset)
        for offset in range(study_days)
    ]

    schedule: list[dict[str, Any]] = []

    # Reserve the final days for consolidation whenever enough time exists.
    if study_days >= 4:
        final_tasks = [
            "Full syllabus revision",
            "Practice questions and weak topics",
            "Mock test and error review",
        ]
        learning_dates = available_dates[:-3]
        final_dates = available_dates[-3:]
    elif study_days == 3:
        final_tasks = [
            "Revision and important questions",
            "Mock test and weak-topic review",
        ]
        learning_dates = available_dates[:-2]
        final_dates = available_dates[-2:]
    elif study_days == 2:
        final_tasks = ["Final revision"]
        learning_dates = available_dates[:-1]
        final_dates = available_dates[-1:]
    else:
        final_tasks = []
        learning_dates = available_dates
        final_dates = []

    # Spread syllabus units across all learning days.
    if learning_dates:
        for index, plan_date in enumerate(learning_dates):
            unit_number = (index % unit_count) + 1
            cycle = index // unit_count

            if cycle == 0:
                task = f"Study Unit {unit_number}"
            else:
                task = f"Revise Unit {unit_number} and solve questions"

            schedule.append(
                {
                    "date": plan_date,
                    "task": task,
                    "hours": daily_hours,
                    "stage": "Learning" if cycle == 0 else "Practice",
                }
            )

    for plan_date, task in zip(final_dates, final_tasks):
        schedule.append(
            {
                "date": plan_date,
                "task": task,
                "hours": daily_hours,
                "stage": "Revision",
            }
        )

    return schedule


def build_study_plan_pdf(
    exam: dict[str, Any],
    tasks: list[dict[str, Any]],
    sessions: list[dict[str, Any]],
) -> bytes:
    """Create a printable PDF report for one saved study plan."""

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title="DeadlineLens Study Plan",
        author="DeadlineLens",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "DeadlineLensTitle",
        parent=styles["Title"],
        alignment=TA_CENTER,
        fontSize=20,
        leading=24,
        spaceAfter=10,
    )
    heading_style = ParagraphStyle(
        "DeadlineLensHeading",
        parent=styles["Heading2"],
        fontSize=13,
        leading=16,
        spaceBefore=8,
        spaceAfter=6,
    )
    body_style = styles["BodyText"]
    small_style = ParagraphStyle(
        "DeadlineLensSmall",
        parent=styles["BodyText"],
        fontSize=8,
        leading=10,
    )

    subject = html.escape(str(exam.get("subject") or "No subject"))
    title = html.escape(str(exam.get("title") or "Examination"))
    deadline_value = exam.get("deadline_datetime")
    if isinstance(deadline_value, datetime):
        exam_date_text = deadline_value.strftime("%d %B %Y, %I:%M %p")
    else:
        exam_date_text = str(exam.get("deadline", "Unknown"))

    completed_count = sum(bool(task.get("completed")) for task in tasks)
    total_count = len(tasks)
    progress_percent = round((completed_count / total_count) * 100) if total_count else 0
    total_hours = sum(float(session.get("duration_minutes", 0)) for session in sessions) / 60

    story = [
        Paragraph("DeadlineLens Study Plan", title_style),
        Paragraph(f"<b>{subject}</b> - {title}", styles["Heading2"]),
        Paragraph(f"Exam date: {html.escape(exam_date_text)}", body_style),
        Paragraph(
            f"Progress: {completed_count}/{total_count} tasks ({progress_percent}%) &nbsp;&nbsp; "
            f"Logged study time: {total_hours:.1f} hours",
            body_style,
        ),
        Spacer(1, 8),
        Paragraph("Study Schedule", heading_style),
    ]

    task_rows = [["Date", "Task", "Stage", "Hours", "Status"]]
    for task in tasks:
        try:
            task_date = datetime.fromisoformat(str(task.get("task_date", ""))).strftime("%d-%m-%Y")
        except ValueError:
            task_date = str(task.get("task_date", ""))
        task_rows.append(
            [
                task_date,
                Paragraph(html.escape(str(task.get("task", ""))), small_style),
                html.escape(str(task.get("stage", ""))),
                f"{float(task.get('hours', 0)):.1f}",
                "Completed" if bool(task.get("completed")) else "Pending",
            ]
        )

    task_table = Table(
        task_rows,
        repeatRows=1,
        colWidths=[24 * mm, 73 * mm, 28 * mm, 16 * mm, 25 * mm],
    )
    task_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#243B53")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F5F8")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(task_table)

    if sessions:
        story.extend([PageBreak(), Paragraph("Study Session Log", heading_style)])
        session_rows = [["Date", "Topic", "Minutes", "Notes"]]
        for session in sessions:
            session_rows.append(
                [
                    html.escape(str(session.get("session_date", ""))),
                    Paragraph(html.escape(str(session.get("topic", ""))), small_style),
                    str(session.get("duration_minutes", 0)),
                    Paragraph(html.escape(str(session.get("notes", ""))), small_style),
                ]
            )
        session_table = Table(
            session_rows,
            repeatRows=1,
            colWidths=[28 * mm, 55 * mm, 20 * mm, 63 * mm],
        )
        session_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#486581")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.grey),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F5F8")]),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(session_table)

    story.extend(
        [
            Spacer(1, 10),
            Paragraph(
                f"Generated by DeadlineLens on {datetime.now().strftime('%d %B %Y at %I:%M %p')}",
                small_style,
            ),
        ]
    )
    document.build(story)
    return buffer.getvalue()


def build_study_plan_csv(tasks: list[dict[str, Any]]) -> bytes:
    """Create a CSV export for one saved study plan."""

    rows = []
    for task in tasks:
        rows.append(
            {
                "Date": task.get("task_date", ""),
                "Task": task.get("task", ""),
                "Stage": task.get("stage", ""),
                "Hours": task.get("hours", 0),
                "Status": "Completed" if bool(task.get("completed")) else "Pending",
            }
        )
    return pd.DataFrame(rows).to_csv(index=False).encode("utf-8-sig")


def show_study_planner() -> None:
    st.header("🤖 Smart Study Planner — Phase 12")
    st.caption(
        "Track preparation, receive smart recommendations, and export a complete study report for printing or sharing."
    )

    deadlines = get_all_deadlines()

    today = datetime.now().date()
    upcoming_exams: list[dict[str, Any]] = []

    for deadline in deadlines:
        if deadline.get("status") == "Completed":
            continue
        try:
            deadline_datetime = datetime.fromisoformat(deadline["deadline"])
        except (KeyError, TypeError, ValueError):
            continue
        if deadline_datetime.date() <= today:
            continue

        title_text = str(deadline.get("title", "")).upper()
        subject_text = str(deadline.get("subject", "")).upper()
        if (
            "EXAM" in title_text
            or "EXAMINATION" in title_text
            or "CA" in subject_text
            or "BA" in subject_text
        ):
            upcoming_exams.append(
                {**deadline, "deadline_datetime": deadline_datetime}
            )

    upcoming_exams.sort(key=lambda item: item["deadline_datetime"])
    if not upcoming_exams:
        st.info(
            "No upcoming saved examinations were found. "
            "Upload and save an examination timetable first."
        )
        return

    exam_options = {
        (
            f"{exam.get('subject') or 'No subject'} — "
            f"{exam['title']} — "
            f"{exam['deadline_datetime'].strftime('%d %b %Y')}"
        ): exam
        for exam in upcoming_exams
    }
    selected_label = st.selectbox(
        "Select examination",
        list(exam_options.keys()),
        key="study_plan_exam",
    )
    selected_exam = exam_options[selected_label]
    deadline_id = int(selected_exam["id"])

    left, right = st.columns(2)
    with left:
        unit_count = st.number_input(
            "Number of syllabus units", min_value=1, max_value=20,
            value=5, step=1, key="study_plan_units",
        )
    with right:
        daily_hours = st.number_input(
            "Study hours per day", min_value=0.5, max_value=8.0,
            value=float(load_app_settings().get("default_study_hours", 2.0)),
            step=0.5, key="study_plan_hours",
        )

    exam_date = selected_exam["deadline_datetime"].date()
    days_remaining = (exam_date - today).days
    metric_one, metric_two, metric_three = st.columns(3)
    metric_one.metric("Days remaining", days_remaining)
    metric_two.metric("Syllabus units", int(unit_count))
    metric_three.metric(
        "Planned study time",
        f"{round(days_remaining * float(daily_hours), 1)} hrs",
    )

    generated_schedule = build_exam_study_schedule(
        selected_exam, int(unit_count), float(daily_hours)
    )

    saved_tasks = get_study_tasks(deadline_id)
    save_label = "Replace saved plan" if saved_tasks else "Save study plan"
    save_col, delete_col = st.columns(2)

    with save_col:
        if st.button(
            f"💾 {save_label}", type="primary",
            key=f"save_study_plan_{deadline_id}", width="stretch",
        ):
            if not generated_schedule:
                st.warning("A plan cannot be generated for this examination.")
            else:
                count = replace_study_plan(deadline_id, generated_schedule)
                st.success(f"{count} study task(s) saved successfully.")
                st.rerun()

    with delete_col:
        if saved_tasks and st.button(
            "🗑️ Delete saved plan",
            key=f"delete_study_plan_{deadline_id}", width="stretch",
        ):
            delete_study_plan(deadline_id)
            st.success("Saved study plan deleted.")
            st.rerun()

    saved_tasks = get_study_tasks(deadline_id)
    if saved_tasks:
        st.subheader("✅ Saved Study Plan")
        completed_count = sum(bool(task["completed"]) for task in saved_tasks)
        total_count = len(saved_tasks)
        progress = completed_count / total_count if total_count else 0.0

        progress_left, progress_right = st.columns([4, 1])
        with progress_left:
            st.progress(progress)
        with progress_right:
            st.metric("Progress", f"{round(progress * 100)}%")
        st.caption(f"{completed_count} of {total_count} tasks completed")

        # Phase 12: export and share center.
        st.subheader("📤 Export & Share")
        current_sessions = get_study_sessions(deadline_id)
        safe_subject = re.sub(
            r"[^A-Za-z0-9_-]+",
            "_",
            str(selected_exam.get("subject") or "exam"),
        ).strip("_") or "exam"
        pdf_bytes = build_study_plan_pdf(
            selected_exam,
            saved_tasks,
            current_sessions,
        )
        csv_bytes = build_study_plan_csv(saved_tasks)
        export_pdf_col, export_csv_col = st.columns(2)
        with export_pdf_col:
            st.download_button(
                "📄 Download PDF report",
                data=pdf_bytes,
                file_name=f"DeadlineLens_{safe_subject}_study_plan.pdf",
                mime="application/pdf",
                key=f"download_study_pdf_{deadline_id}",
                width="stretch",
            )
        with export_csv_col:
            st.download_button(
                "📊 Download CSV schedule",
                data=csv_bytes,
                file_name=f"DeadlineLens_{safe_subject}_study_plan.csv",
                mime="text/csv",
                key=f"download_study_csv_{deadline_id}",
                width="stretch",
            )
        st.caption(
            "The PDF includes exam details, progress, the complete schedule, "
            "and the study-session log."
        )

        # Phase 3: Today's Focus and schedule-aware task groups.
        pending_tasks = [task for task in saved_tasks if not bool(task["completed"])]
        overdue_tasks = []
        today_tasks = []
        upcoming_tasks = []

        for task in pending_tasks:
            try:
                task_day = datetime.fromisoformat(task["task_date"]).date()
            except (TypeError, ValueError):
                continue

            if task_day < today:
                overdue_tasks.append(task)
            elif task_day == today:
                today_tasks.append(task)
            else:
                upcoming_tasks.append(task)

        # Phase 5: exam-readiness score and targeted recommendations.
        completion_component = progress * 70
        overdue_ratio = (len(overdue_tasks) / total_count) if total_count else 0.0
        schedule_component = max(0.0, 20.0 - (overdue_ratio * 40.0))
        time_component = min(10.0, max(0.0, days_remaining / 7 * 10.0))
        readiness_score = round(
            min(100.0, completion_component + schedule_component + time_component)
        )

        learning_tasks = [task for task in saved_tasks if task.get("stage") == "Learning"]
        revision_tasks = [task for task in saved_tasks if task.get("stage") == "Revision"]
        completed_learning = sum(bool(task["completed"]) for task in learning_tasks)
        completed_revision = sum(bool(task["completed"]) for task in revision_tasks)

        st.subheader("📈 Exam Readiness")
        ready_one, ready_two, ready_three, ready_four = st.columns(4)
        ready_one.metric("Readiness score", f"{readiness_score}%")
        ready_two.metric(
            "Learning",
            f"{completed_learning}/{len(learning_tasks)}",
        )
        ready_three.metric(
            "Revision",
            f"{completed_revision}/{len(revision_tasks)}",
        )
        ready_four.metric("Days to exam", days_remaining)
        st.progress(readiness_score / 100)

        if overdue_tasks:
            st.warning(
                f"Recommended action: rebalance the {len(overdue_tasks)} overdue "
                "task(s), then complete the earliest rescheduled task today."
            )
        elif readiness_score < 40:
            st.warning(
                "Recommended action: complete today’s task and increase consistency "
                "before beginning revision."
            )
        elif readiness_score < 70:
            st.info(
                "Recommended action: continue the current schedule and begin practice "
                "questions as soon as the learning tasks are complete."
            )
        elif readiness_score < 90:
            st.success(
                "You are progressing well. Prioritize revision and one timed mock test."
            )
        else:
            st.success(
                "Excellent readiness. Focus on light revision, weak topics, and rest."
            )

        # Phase 6: weekly study insights and consistency streak.
        st.subheader("📊 Weekly Study Insights")
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)

        weekly_tasks = []
        daily_summary: dict[date, dict[str, float | int]] = {}

        for task in saved_tasks:
            try:
                task_day = datetime.fromisoformat(task["task_date"]).date()
            except (TypeError, ValueError):
                continue

            if week_start <= task_day <= week_end:
                weekly_tasks.append(task)

            day_data = daily_summary.setdefault(
                task_day,
                {"planned": 0, "completed": 0, "hours": 0.0},
            )
            day_data["planned"] += 1
            if bool(task["completed"]):
                day_data["completed"] += 1
                day_data["hours"] += float(task.get("hours", 0) or 0)

        weekly_completed = sum(
            bool(task["completed"]) for task in weekly_tasks
        )
        weekly_planned_hours = sum(
            float(task.get("hours", 0) or 0) for task in weekly_tasks
        )
        weekly_completed_hours = sum(
            float(task.get("hours", 0) or 0)
            for task in weekly_tasks
            if bool(task["completed"])
        )
        weekly_rate = (
            weekly_completed / len(weekly_tasks)
            if weekly_tasks
            else 0.0
        )

        # A streak day counts when every scheduled task for that day is complete.
        study_streak = 0
        streak_day = today
        while True:
            day_data = daily_summary.get(streak_day)
            if not day_data:
                # Skip today when no task was scheduled yet, but stop on older gaps.
                if streak_day == today:
                    streak_day -= timedelta(days=1)
                    continue
                break
            if day_data["planned"] and day_data["completed"] == day_data["planned"]:
                study_streak += 1
                streak_day -= timedelta(days=1)
            else:
                break

        insight_one, insight_two, insight_three, insight_four = st.columns(4)
        insight_one.metric("Tasks this week", f"{weekly_completed}/{len(weekly_tasks)}")
        insight_two.metric("Weekly completion", f"{round(weekly_rate * 100)}%")
        insight_three.metric(
            "Hours completed",
            f"{round(weekly_completed_hours, 1)}/{round(weekly_planned_hours, 1)} h",
        )
        insight_four.metric("Study streak", f"{study_streak} day(s)")

        st.progress(weekly_rate)
        st.caption(
            f"Current week: {week_start.strftime('%d %b')} – "
            f"{week_end.strftime('%d %b %Y')}"
        )

        chart_rows = []
        for offset in range(7):
            chart_day = week_start + timedelta(days=offset)
            chart_data = daily_summary.get(
                chart_day,
                {"planned": 0, "completed": 0},
            )
            chart_rows.append(
                {
                    "Day": chart_day.strftime("%a"),
                    "Planned": int(chart_data["planned"]),
                    "Completed": int(chart_data["completed"]),
                }
            )

        chart_frame = pd.DataFrame(chart_rows)
        chart_long = chart_frame.melt(
            id_vars="Day",
            value_vars=["Planned", "Completed"],
            var_name="Task status",
            value_name="Tasks",
        )
        weekly_chart = px.bar(
            chart_long,
            x="Day",
            y="Tasks",
            color="Task status",
            barmode="group",
            title="Planned vs completed tasks this week",
        )
        weekly_chart.update_layout(
            margin=dict(l=10, r=10, t=50, b=10),
            legend_title_text="",
        )
        st.plotly_chart(weekly_chart, width="stretch")

        if weekly_tasks and weekly_rate < 0.5:
            st.warning(
                "Weekly consistency is below 50%. Complete today’s focus task or "
                "rebalance overdue work to recover the schedule."
            )
        elif weekly_tasks and weekly_rate >= 0.8:
            st.success(
                "Strong weekly consistency — keep the same pace and protect your "
                "revision days."
            )
        elif not weekly_tasks:
            st.info("No study tasks are scheduled for the current week.")

        # Phase 7: completion forecast and schedule adherence.
        st.subheader("🔮 Completion Forecast")

        remaining_tasks = len(pending_tasks)
        remaining_study_days = max(1, (exam_date - today).days)
        required_tasks_per_day = remaining_tasks / remaining_study_days

        scheduled_by_today = []
        completed_by_today = []
        for task in saved_tasks:
            try:
                task_day = datetime.fromisoformat(task["task_date"]).date()
            except (TypeError, ValueError):
                continue
            if task_day <= today:
                scheduled_by_today.append(task)
                if bool(task["completed"]):
                    completed_by_today.append(task)

        adherence_rate = (
            len(completed_by_today) / len(scheduled_by_today)
            if scheduled_by_today
            else 1.0
        )

        if remaining_tasks == 0:
            forecast_status = "Complete"
            forecast_message = (
                "All study tasks are complete. Use the remaining time for light "
                "revision, weak topics, and rest."
            )
        elif overdue_tasks:
            forecast_status = "Needs attention"
            forecast_message = (
                f"You have {len(overdue_tasks)} overdue task(s). Rebalance the plan "
                "or complete the earliest overdue task today."
            )
        elif required_tasks_per_day <= 1:
            forecast_status = "On track"
            forecast_message = (
                "Your remaining workload is manageable at approximately "
                f"{required_tasks_per_day:.1f} task per day."
            )
        elif required_tasks_per_day <= 2:
            forecast_status = "Tight schedule"
            forecast_message = (
                "The plan is achievable, but you should complete about "
                f"{required_tasks_per_day:.1f} tasks per day."
            )
        else:
            forecast_status = "At risk"
            forecast_message = (
                "The remaining workload is heavy. Rebalance the plan and increase "
                "daily study time where possible."
            )

        forecast_one, forecast_two, forecast_three, forecast_four = st.columns(4)
        forecast_one.metric("Forecast", forecast_status)
        forecast_two.metric("Tasks remaining", remaining_tasks)
        forecast_three.metric(
            "Required pace",
            f"{required_tasks_per_day:.1f}/day",
        )
        forecast_four.metric(
            "Schedule adherence",
            f"{round(adherence_rate * 100)}%",
        )

        if forecast_status in {"At risk", "Needs attention"}:
            st.warning(forecast_message)
        elif forecast_status == "Tight schedule":
            st.info(forecast_message)
        else:
            st.success(forecast_message)

        cumulative_rows = []
        cumulative_planned = 0
        cumulative_completed = 0
        for task_day in sorted(daily_summary):
            if task_day > exam_date:
                continue
            day_data = daily_summary[task_day]
            cumulative_planned += int(day_data["planned"])
            cumulative_completed += int(day_data["completed"])
            cumulative_rows.append(
                {
                    "Date": task_day,
                    "Planned": cumulative_planned,
                    "Completed": cumulative_completed,
                }
            )

        if cumulative_rows:
            cumulative_frame = pd.DataFrame(cumulative_rows)
            cumulative_long = cumulative_frame.melt(
                id_vars="Date",
                value_vars=["Planned", "Completed"],
                var_name="Progress type",
                value_name="Cumulative tasks",
            )
            forecast_chart = px.line(
                cumulative_long,
                x="Date",
                y="Cumulative tasks",
                color="Progress type",
                markers=True,
                title="Cumulative planned vs completed progress",
            )
            forecast_chart.update_layout(
                margin=dict(l=10, r=10, t=50, b=10),
                legend_title_text="",
            )
            st.plotly_chart(forecast_chart, width="stretch")


        # Phase 8: record actual study sessions and compare effort with the plan.
        st.subheader("⏱️ Study Session Tracker")
        saved_sessions = get_study_sessions(deadline_id)
        total_minutes = sum(int(item.get("minutes", 0) or 0) for item in saved_sessions)
        sessions_this_week = []
        week_start_for_sessions = today - timedelta(days=today.weekday())
        for item in saved_sessions:
            try:
                session_day = datetime.fromisoformat(item["session_date"]).date()
            except (TypeError, ValueError):
                continue
            if week_start_for_sessions <= session_day <= today:
                sessions_this_week.append(item)

        tracker_one, tracker_two, tracker_three = st.columns(3)
        tracker_one.metric("Sessions logged", len(saved_sessions))
        tracker_two.metric("Actual study time", f"{total_minutes / 60:.1f} h")
        tracker_three.metric(
            "This week",
            f"{sum(int(item.get('minutes', 0) or 0) for item in sessions_this_week) / 60:.1f} h",
        )

        with st.form(f"study_session_form_{deadline_id}", clear_on_submit=True):
            session_date_col, duration_col = st.columns(2)
            with session_date_col:
                session_date = st.date_input(
                    "Session date",
                    value=today,
                    max_value=today,
                    key=f"session_date_{deadline_id}",
                )
            with duration_col:
                session_minutes = st.number_input(
                    "Duration in minutes",
                    min_value=10,
                    max_value=600,
                    value=60,
                    step=10,
                    key=f"session_minutes_{deadline_id}",
                )
            session_topic = st.text_input(
                "Topic studied",
                placeholder="Example: Unit 2 — Data Structures",
                key=f"session_topic_{deadline_id}",
            )
            session_notes = st.text_area(
                "Notes (optional)",
                placeholder="What did you complete or find difficult?",
                key=f"session_notes_{deadline_id}",
            )
            session_submitted = st.form_submit_button(
                "➕ Log study session",
                type="primary",
                width="stretch",
            )

        if session_submitted:
            if not session_topic.strip():
                st.warning("Please enter the topic you studied.")
            else:
                add_study_session(
                    deadline_id=deadline_id,
                    session_date=session_date,
                    topic=session_topic,
                    minutes=int(session_minutes),
                    notes=session_notes,
                )
                st.success("Study session recorded successfully.")
                st.rerun()

        if saved_sessions:
            with st.expander("Recent study sessions", expanded=False):
                for session in saved_sessions[:10]:
                    session_day = datetime.fromisoformat(
                        session["session_date"]
                    ).date()
                    with st.container(border=True):
                        session_detail, session_duration, session_action = st.columns([6, 2, 1])
                        with session_detail:
                            st.markdown(f"**{session['topic']}**")
                            st.caption(session_day.strftime("%A, %d %b %Y"))
                            if session.get("notes"):
                                st.write(session["notes"])
                        with session_duration:
                            st.metric("Duration", f"{int(session['minutes'])} min")
                        with session_action:
                            if st.button(
                                "🗑️",
                                key=f"delete_session_{session['id']}",
                                help="Delete this session",
                            ):
                                delete_study_session(int(session["id"]))
                                st.rerun()


        # Phase 9: daily study goal and productivity score.
        st.subheader("🏆 Daily Goal & Productivity")
        daily_target_minutes = get_study_goal(deadline_id)

        goal_settings_col, goal_save_col = st.columns([3, 1])
        with goal_settings_col:
            selected_daily_target = st.slider(
                "Daily study target (minutes)",
                min_value=15,
                max_value=360,
                value=int(daily_target_minutes),
                step=15,
                key=f"daily_goal_{deadline_id}",
            )
        with goal_save_col:
            st.write("")
            st.write("")
            if st.button(
                "Save target",
                key=f"save_daily_goal_{deadline_id}",
                width="stretch",
            ):
                set_study_goal(deadline_id, int(selected_daily_target))
                st.success("Daily study target saved.")
                st.rerun()

        minutes_by_day: dict = {}
        for session in saved_sessions:
            try:
                session_day = datetime.fromisoformat(session["session_date"]).date()
            except (TypeError, ValueError):
                continue
            minutes_by_day[session_day] = (
                minutes_by_day.get(session_day, 0)
                + int(session.get("minutes", 0) or 0)
            )

        today_minutes = minutes_by_day.get(today, 0)
        target_minutes = max(int(daily_target_minutes), 1)
        goal_progress = min(today_minutes / target_minutes, 1.0)

        last_seven_days = [today - timedelta(days=offset) for offset in range(6, -1, -1)]
        days_goal_reached = sum(
            1 for day_value in last_seven_days
            if minutes_by_day.get(day_value, 0) >= target_minutes
        )
        seven_day_minutes = sum(minutes_by_day.get(day_value, 0) for day_value in last_seven_days)
        expected_minutes = target_minutes * 7
        productivity_score = min(
            100,
            round((seven_day_minutes / expected_minutes) * 100),
        ) if expected_minutes else 0

        goal_one, goal_two, goal_three, goal_four = st.columns(4)
        goal_one.metric("Studied today", f"{today_minutes} min")
        goal_two.metric("Daily target", f"{target_minutes} min")
        goal_three.metric("Goals reached", f"{days_goal_reached}/7 days")
        goal_four.metric("Productivity score", f"{productivity_score}%")

        st.progress(goal_progress)
        if today_minutes >= target_minutes:
            st.success("Daily goal achieved. Great work!")
        elif today_minutes > 0:
            st.info(
                f"{target_minutes - today_minutes} more minute(s) needed "
                "to reach today's goal."
            )
        else:
            st.warning("No study time has been logged today yet.")

        goal_chart_rows = [
            {
                "Date": day_value,
                "Minutes studied": minutes_by_day.get(day_value, 0),
                "Daily target": target_minutes,
            }
            for day_value in last_seven_days
        ]
        goal_chart_frame = pd.DataFrame(goal_chart_rows)
        goal_chart_long = goal_chart_frame.melt(
            id_vars="Date",
            value_vars=["Minutes studied", "Daily target"],
            var_name="Measure",
            value_name="Minutes",
        )
        goal_chart = px.bar(
            goal_chart_long,
            x="Date",
            y="Minutes",
            color="Measure",
            barmode="group",
            title="Last 7 days: actual study time vs daily target",
        )
        goal_chart.update_layout(
            margin=dict(l=10, r=10, t=50, b=10),
            legend_title_text="",
        )
        st.plotly_chart(goal_chart, width="stretch")

        # Phase 10: achievements and study milestones.
        st.subheader("🏅 Achievements & Milestones")

        total_sessions = len(saved_sessions)
        total_logged_minutes = sum(
            int(session.get("minutes", 0) or 0)
            for session in saved_sessions
        )
        total_logged_hours = total_logged_minutes / 60
        completed_task_count = sum(
            1 for task in saved_tasks if bool(task.get("completed"))
        )
        total_task_count = len(saved_tasks)
        task_completion_percent = (
            round((completed_task_count / total_task_count) * 100)
            if total_task_count
            else 0
        )

        # Calculate consecutive study-day streak ending today or yesterday.
        studied_days = {
            day_value
            for day_value, minutes in minutes_by_day.items()
            if minutes > 0
        }
        streak = 0
        streak_day = today
        if streak_day not in studied_days:
            streak_day = today - timedelta(days=1)
        while streak_day in studied_days:
            streak += 1
            streak_day -= timedelta(days=1)

        achievement_definitions = [
            {
                "icon": "🌱",
                "name": "First Step",
                "description": "Log your first study session.",
                "unlocked": total_sessions >= 1,
                "progress": min(total_sessions, 1),
                "target": 1,
            },
            {
                "icon": "📚",
                "name": "Study Habit",
                "description": "Complete 5 study sessions.",
                "unlocked": total_sessions >= 5,
                "progress": min(total_sessions, 5),
                "target": 5,
            },
            {
                "icon": "⏳",
                "name": "Ten-Hour Scholar",
                "description": "Log 10 total study hours.",
                "unlocked": total_logged_hours >= 10,
                "progress": min(total_logged_hours, 10),
                "target": 10,
            },
            {
                "icon": "🔥",
                "name": "Three-Day Streak",
                "description": "Study on 3 consecutive days.",
                "unlocked": streak >= 3,
                "progress": min(streak, 3),
                "target": 3,
            },
            {
                "icon": "🎯",
                "name": "Halfway Hero",
                "description": "Complete 50% of the study plan.",
                "unlocked": task_completion_percent >= 50,
                "progress": min(task_completion_percent, 50),
                "target": 50,
            },
            {
                "icon": "🏆",
                "name": "Plan Master",
                "description": "Complete every task in the study plan.",
                "unlocked": bool(total_task_count) and task_completion_percent == 100,
                "progress": task_completion_percent,
                "target": 100,
            },
        ]

        unlocked_count = sum(
            1 for achievement in achievement_definitions
            if achievement["unlocked"]
        )
        badge_one, badge_two, badge_three, badge_four = st.columns(4)
        badge_one.metric("Achievements", f"{unlocked_count}/{len(achievement_definitions)}")
        badge_two.metric("Current streak", f"{streak} day(s)")
        badge_three.metric("Study sessions", total_sessions)
        badge_four.metric("Logged study", f"{total_logged_hours:.1f} h")

        achievement_columns = st.columns(2)
        for achievement_index, achievement in enumerate(achievement_definitions):
            with achievement_columns[achievement_index % 2]:
                with st.container(border=True):
                    status = "Unlocked" if achievement["unlocked"] else "Locked"
                    st.markdown(
                        f"### {achievement['icon']} {achievement['name']}"
                    )
                    st.caption(f"{status} • {achievement['description']}")
                    achievement_progress = min(
                        float(achievement["progress"]) / float(achievement["target"]),
                        1.0,
                    )
                    st.progress(achievement_progress)
                    if achievement["target"] == 50 or achievement["target"] == 100:
                        st.caption(
                            f"Progress: {int(achievement['progress'])}% / "
                            f"{achievement['target']}%"
                        )
                    elif achievement["name"] == "Ten-Hour Scholar":
                        st.caption(
                            f"Progress: {float(achievement['progress']):.1f} / "
                            f"{achievement['target']} hours"
                        )
                    else:
                        st.caption(
                            f"Progress: {int(achievement['progress'])} / "
                            f"{achievement['target']}"
                        )

        if unlocked_count == len(achievement_definitions):
            st.success("All achievements unlocked — outstanding consistency!")
        elif unlocked_count:
            st.info(
                f"You have unlocked {unlocked_count} achievement(s). "
                "Keep studying to unlock the remaining badges."
            )
        else:
            st.info("Log your first study session to unlock your first badge.")

        # Phase 11: smart performance analysis and recommendations.
        st.subheader("🧠 Smart Performance Analyzer")

        completion_score = min(100.0, float(task_completion_percent))
        consistency_score = min(100.0, (streak / 7.0) * 100.0)
        goal_score = min(100.0, float(productivity_score))
        revision_score = (
            (completed_revision / len(revision_tasks)) * 100.0
            if revision_tasks
            else completion_score
        )
        schedule_score = max(
            0.0,
            100.0 - (len(overdue_tasks) / max(total_task_count, 1)) * 100.0,
        )

        performance_score = round(
            completion_score * 0.35
            + consistency_score * 0.15
            + goal_score * 0.20
            + revision_score * 0.15
            + schedule_score * 0.15
        )

        time_pressure_penalty = 0
        if days_remaining <= 3 and task_completion_percent < 80:
            time_pressure_penalty = 12
        elif days_remaining <= 7 and task_completion_percent < 60:
            time_pressure_penalty = 7

        confidence_score = max(
            0,
            min(100, round((performance_score + readiness_score) / 2) - time_pressure_penalty),
        )

        if confidence_score >= 80:
            confidence_label = "High"
            confidence_message = "You are well prepared. Focus on revision and exam practice."
        elif confidence_score >= 60:
            confidence_label = "Moderate"
            confidence_message = "You are progressing well, but a few focused sessions will improve readiness."
        elif confidence_score >= 40:
            confidence_label = "Developing"
            confidence_message = "Your preparation needs more consistency and task completion."
        else:
            confidence_label = "At risk"
            confidence_message = "Immediate action is recommended to recover the study plan."

        analyzer_one, analyzer_two, analyzer_three, analyzer_four = st.columns(4)
        analyzer_one.metric("Performance score", f"{performance_score}/100")
        analyzer_two.metric("Exam confidence", f"{confidence_score}%")
        analyzer_three.metric("Confidence level", confidence_label)
        analyzer_four.metric("Schedule adherence", f"{round(schedule_score)}%")

        st.progress(confidence_score / 100.0)
        if confidence_score >= 80:
            st.success(confidence_message)
        elif confidence_score >= 60:
            st.info(confidence_message)
        else:
            st.warning(confidence_message)

        score_breakdown = pd.DataFrame(
            [
                {"Category": "Plan completion", "Score": round(completion_score)},
                {"Category": "Study consistency", "Score": round(consistency_score)},
                {"Category": "Daily goals", "Score": round(goal_score)},
                {"Category": "Revision completion", "Score": round(revision_score)},
                {"Category": "Schedule adherence", "Score": round(schedule_score)},
            ]
        )
        score_chart = px.bar(
            score_breakdown,
            x="Category",
            y="Score",
            range_y=[0, 100],
            title="Preparation score breakdown",
            text="Score",
        )
        score_chart.update_layout(margin=dict(l=10, r=10, t=50, b=10))
        st.plotly_chart(score_chart, width="stretch")

        recommendations: list[str] = []
        if overdue_tasks:
            recommendations.append(
                f"Complete or rebalance {len(overdue_tasks)} overdue task(s) first."
            )
        if productivity_score < 70:
            recommendations.append(
                "Increase study consistency by meeting the daily goal on more days this week."
            )
        if revision_tasks and revision_score < 60:
            recommendations.append(
                "Prioritize revision tasks before adding new learning work."
            )
        if total_logged_hours < max(2.0, days_remaining * float(daily_hours) * 0.25):
            recommendations.append(
                "Log more focused study sessions so actual study time matches the plan."
            )
        if days_remaining <= 7 and task_completion_percent < 75:
            recommendations.append(
                "Use shorter, high-priority sessions because the examination is less than a week away."
            )
        if not recommendations:
            recommendations.append(
                "Maintain the current pace and schedule a final revision plus one mock test."
            )

        st.markdown("#### Recommended next actions")
        for recommendation in recommendations[:4]:
            st.write(f"• {recommendation}")

        if saved_sessions:
            trend_start = today - timedelta(days=13)
            trend_rows = []
            for offset in range(14):
                trend_day = trend_start + timedelta(days=offset)
                trend_rows.append(
                    {
                        "Date": trend_day,
                        "Study minutes": minutes_by_day.get(trend_day, 0),
                    }
                )
            trend_frame = pd.DataFrame(trend_rows)
            trend_chart = px.line(
                trend_frame,
                x="Date",
                y="Study minutes",
                markers=True,
                title="Study-time trend — last 14 days",
            )
            trend_chart.update_layout(margin=dict(l=10, r=10, t=50, b=10))
            st.plotly_chart(trend_chart, width="stretch")

        st.subheader("🎯 Today's Focus")
        focus_one, focus_two, focus_three = st.columns(3)
        focus_one.metric("Due today", len(today_tasks))
        focus_two.metric("Overdue", len(overdue_tasks))
        focus_three.metric("Upcoming", len(upcoming_tasks))

        if overdue_tasks:
            st.error(
                f"{len(overdue_tasks)} unfinished task(s) are overdue. "
                "You can rebalance all unfinished tasks across the remaining study days."
            )

            if st.button(
                "🔄 Rebalance unfinished tasks",
                type="primary",
                key=f"rebalance_plan_{deadline_id}",
                width="stretch",
            ):
                moved_count = rebalance_study_plan(
                    deadline_id=deadline_id,
                    start_date=today,
                    exam_date=exam_date,
                )

                if moved_count:
                    st.success(
                        f"{moved_count} unfinished task(s) were redistributed "
                        "across the remaining study days."
                    )
                else:
                    st.warning(
                        "The plan could not be rebalanced because no study days "
                        "remain before the examination."
                    )

                st.rerun()

        focus_tasks = overdue_tasks + today_tasks
        if focus_tasks:
            for task in focus_tasks:
                task_date = datetime.fromisoformat(task["task_date"]).date()
                status_label = "OVERDUE" if task_date < today else "TODAY"
                with st.container(border=True):
                    focus_check, focus_detail, focus_time = st.columns([1, 6, 1])
                    with focus_check:
                        focus_done = st.checkbox(
                            "Complete focus task",
                            value=False,
                            key=f"focus_task_{task['id']}",
                            label_visibility="collapsed",
                        )
                    if focus_done:
                        update_study_task_completion(int(task["id"]), True)
                        st.rerun()
                    with focus_detail:
                        st.markdown(f"**{task['task']}**")
                        st.caption(
                            f"{status_label} • {task_date.strftime('%A, %d %b %Y')} "
                            f"• Stage: {task['stage']}"
                        )
                    with focus_time:
                        st.metric("Time", f"{task['hours']} h")
        elif pending_tasks:
            next_task = min(
                pending_tasks,
                key=lambda item: item["task_date"],
            )
            next_date = datetime.fromisoformat(next_task["task_date"]).date()
            st.success(
                "You are up to date. Your next task is "
                f"‘{next_task['task']}’ on {next_date.strftime('%d %b %Y')}."
            )
        else:
            st.success("Excellent — every task in this study plan is complete! 🎉")

        with st.expander("📋 View complete saved plan", expanded=False):
            for index, task in enumerate(saved_tasks, start=1):
                task_date = datetime.fromisoformat(task["task_date"]).date()
                with st.container(border=True):
                    check_col, detail_col, time_col = st.columns([1, 6, 1])
                    with check_col:
                        checked = st.checkbox(
                            "Done",
                            value=bool(task["completed"]),
                            key=f"study_task_{task['id']}",
                            label_visibility="collapsed",
                        )
                    if checked != bool(task["completed"]):
                        update_study_task_completion(int(task["id"]), checked)
                        st.rerun()
                    with detail_col:
                        task_style = "~~" if checked else "**"
                        st.markdown(f"{task_style}{task['task']}{task_style}")
                        st.caption(
                            f"{task_date.strftime('%A, %d %b %Y')} • "
                            f"Stage: {task['stage']}"
                        )
                    with time_col:
                        st.metric("Time", f"{task['hours']} h")

        st.success(
            "Phase 10 is active: DeadlineLens now rewards study consistency with "
            "achievement badges, streaks, and milestone progress."
        )
        return

    st.subheader("📅 Plan Preview")
    if not generated_schedule:
        st.warning(
            "A study plan cannot be generated because this examination "
            "is today or has already passed."
        )
        return

    preview_rows = [
        {
            "Date": item["date"].strftime("%d-%m-%Y"),
            "Day": item["date"].strftime("%A"),
            "Study task": item["task"],
            "Stage": item["stage"],
            "Hours": item["hours"],
        }
        for item in generated_schedule
    ]
    st.dataframe(preview_rows, width="stretch", hide_index=True)
    st.info(
        "Review the preview, then click Save study plan. "
        "Saved tasks can be marked complete individually."
    )




def show_exam_resources() -> None:
    """Manage notes, links, and study resources for saved examinations."""
    st.header("📚 Exam Notes & Resources")
    st.caption(
        "Keep syllabus notes, useful links, revision points, and reference "
        "material together with each examination."
    )

    deadlines = get_all_deadlines()
    if not deadlines:
        st.info("Save at least one deadline before adding exam resources.")
        return

    selected_id = st.selectbox(
        "Choose an examination",
        options=[int(item["id"]) for item in deadlines],
        format_func=lambda item_id: next(
            (
                f"{item.get('subject') or 'General'} — {item['title']} "
                f"({datetime.fromisoformat(item['deadline']).strftime('%d %b %Y')})"
                for item in deadlines
                if int(item["id"]) == int(item_id)
            ),
            str(item_id),
        ),
        key="resource_deadline_id",
    )

    selected_deadline = next(
        item for item in deadlines if int(item["id"]) == int(selected_id)
    )

    with st.form("add_exam_resource_form", clear_on_submit=True):
        resource_type = st.selectbox(
            "Resource type",
            ["Note", "Web Link", "Book / Reference", "Revision Point", "Other"],
        )
        resource_title = st.text_input(
            "Title",
            placeholder="Example: Unit 1 revision notes",
        )
        resource_content = st.text_area(
            "Content or link",
            placeholder=(
                "Write your note here, or paste a useful web link such as "
                "https://example.com"
            ),
            height=130,
        )
        save_resource = st.form_submit_button(
            "Save resource",
            type="primary",
            width="stretch",
        )

    if save_resource:
        if not resource_title.strip() or not resource_content.strip():
            st.warning("Please enter both a title and content.")
        else:
            add_exam_resource(
                deadline_id=int(selected_id),
                resource_type=resource_type,
                title=resource_title,
                content=resource_content,
            )
            st.success("Resource saved successfully.")
            st.rerun()

    resources = get_exam_resources(int(selected_id))
    st.subheader(
        f"Saved resources for {selected_deadline.get('subject') or selected_deadline['title']}"
    )

    if not resources:
        st.info("No notes or resources have been saved for this examination yet.")
        return

    type_filter = st.multiselect(
        "Filter by type",
        sorted({str(item["resource_type"]) for item in resources}),
        default=sorted({str(item["resource_type"]) for item in resources}),
        key=f"resource_type_filter_{selected_id}",
    )

    filtered_resources = [
        item for item in resources if item["resource_type"] in type_filter
    ]

    for resource in filtered_resources:
        with st.container(border=True):
            title_column, delete_column = st.columns([6, 1])
            with title_column:
                st.markdown(
                    f"### {resource['title']}"
                )
                st.caption(
                    f"{resource['resource_type']} • {resource['created_at']}"
                )
            with delete_column:
                if st.button(
                    "🗑️",
                    key=f"delete_resource_{resource['id']}",
                    help="Delete this resource",
                ):
                    delete_exam_resource(int(resource["id"]))
                    st.success("Resource deleted.")
                    st.rerun()

            content = str(resource["content"]).strip()
            if resource["resource_type"] == "Web Link" and content.lower().startswith(
                ("http://", "https://")
            ):
                st.link_button("Open resource", content)
                st.code(content, language=None)
            else:
                st.write(content)



def show_mock_test_tracker() -> None:
    """Record mock-test scores and show improvement over time."""
    st.header("📝 Mock Test Tracker")
    st.caption(
        "Record practice-test results, monitor accuracy, and identify whether "
        "your examination performance is improving."
    )

    deadlines = get_all_deadlines()
    if not deadlines:
        st.info("Save at least one examination before recording mock tests.")
        return

    selected_id = st.selectbox(
        "Choose an examination",
        options=[int(item["id"]) for item in deadlines],
        format_func=lambda item_id: next(
            (
                f"{item.get('subject') or 'General'} — {item['title']} "
                f"({datetime.fromisoformat(item['deadline']).strftime('%d %b %Y')})"
                for item in deadlines
                if int(item["id"]) == int(item_id)
            ),
            str(item_id),
        ),
        key="mock_test_deadline_id",
    )

    with st.form("add_mock_test_form", clear_on_submit=True):
        column_one, column_two = st.columns(2)
        with column_one:
            test_name = st.text_input(
                "Test name",
                placeholder="Example: Unit 1 Mock Test",
            )
            test_date = st.date_input("Test date", value=datetime.now().date())
            duration_minutes = st.number_input(
                "Duration (minutes)",
                min_value=0,
                max_value=600,
                value=60,
                step=5,
            )
        with column_two:
            score = st.number_input(
                "Score obtained",
                min_value=0.0,
                value=0.0,
                step=1.0,
            )
            total_marks = st.number_input(
                "Total marks",
                min_value=1.0,
                value=100.0,
                step=1.0,
            )
            notes = st.text_area(
                "Notes",
                placeholder="Weak topics, mistakes, or revision points",
                height=100,
            )

        save_test = st.form_submit_button(
            "Save mock-test result",
            type="primary",
            width="stretch",
        )

    if save_test:
        if not test_name.strip():
            st.warning("Please enter a test name.")
        elif score > total_marks:
            st.warning("Score obtained cannot be greater than total marks.")
        else:
            add_mock_test(
                deadline_id=int(selected_id),
                test_date=test_date.isoformat(),
                test_name=test_name,
                score=float(score),
                total_marks=float(total_marks),
                duration_minutes=int(duration_minutes),
                notes=notes,
            )
            st.success("Mock-test result saved.")
            st.rerun()

    tests = get_mock_tests(int(selected_id))
    if not tests:
        st.info("No mock-test results have been recorded for this examination.")
        return

    percentages = [
        (float(item["score"]) / float(item["total_marks"])) * 100
        for item in tests
        if float(item["total_marks"]) > 0
    ]
    latest_percentage = percentages[-1]
    best_percentage = max(percentages)
    average_percentage = sum(percentages) / len(percentages)
    improvement = (
        latest_percentage - percentages[0]
        if len(percentages) > 1
        else 0.0
    )

    metric_one, metric_two, metric_three, metric_four = st.columns(4)
    metric_one.metric("Tests taken", len(tests))
    metric_two.metric("Latest score", f"{latest_percentage:.1f}%")
    metric_three.metric("Best score", f"{best_percentage:.1f}%")
    metric_four.metric(
        "Improvement",
        f"{improvement:+.1f}%",
        help="Difference between the first and latest mock-test percentages.",
    )

    st.progress(min(max(latest_percentage / 100, 0.0), 1.0))
    if latest_percentage >= 80:
        st.success("Strong performance. Focus on final revision and accuracy.")
    elif latest_percentage >= 60:
        st.info("Good progress. Review errors before taking the next mock test.")
    else:
        st.warning("More practice is needed. Revisit weak topics before retesting.")

    chart_data = pd.DataFrame(
        {
            "Test": [item["test_name"] for item in tests],
            "Date": [pd.to_datetime(item["test_date"]) for item in tests],
            "Percentage": percentages,
        }
    )
    figure = px.line(
        chart_data,
        x="Date",
        y="Percentage",
        markers=True,
        hover_name="Test",
        title="Mock-Test Performance Trend",
    )
    figure.update_yaxes(range=[0, 100], title="Score (%)")
    st.plotly_chart(figure, width="stretch")

    st.caption(f"Average score across all tests: {average_percentage:.1f}%")
    st.subheader("Recorded tests")

    for test, percentage in zip(reversed(tests), reversed(percentages)):
        with st.container(border=True):
            heading_column, delete_column = st.columns([6, 1])
            with heading_column:
                st.markdown(f"### {test['test_name']}")
                st.caption(
                    f"{datetime.fromisoformat(test['test_date']).strftime('%d %b %Y')} "
                    f"• {test['duration_minutes']} minutes"
                )
            with delete_column:
                if st.button(
                    "🗑️",
                    key=f"delete_mock_test_{test['id']}",
                    help="Delete this result",
                ):
                    delete_mock_test(int(test["id"]))
                    st.success("Mock-test result deleted.")
                    st.rerun()

            st.write(
                f"**Score:** {test['score']:g}/{test['total_marks']:g} "
                f"({percentage:.1f}%)"
            )
            if str(test.get("notes") or "").strip():
                st.write(f"**Notes:** {test['notes']}")

def show_backup_center() -> None:
    """Display database backup and portable data export options."""
    st.header("💾 Backup & Data Export — Phase 13")
    st.caption(
        "Create safe copies of your deadlines, reminders, study plans, "
        "study sessions, and goals."
    )

    snapshot = export_database_snapshot()
    deadlines = snapshot.get("deadlines", [])
    tasks = snapshot.get("study_tasks", [])
    sessions = snapshot.get("study_sessions", [])
    reminders = snapshot.get("reminder_history", [])

    metric_one, metric_two, metric_three, metric_four = st.columns(4)
    metric_one.metric("Deadlines", len(deadlines))
    metric_two.metric("Study tasks", len(tasks))
    metric_three.metric("Study sessions", len(sessions))
    metric_four.metric("Reminder records", len(reminders))

    generated_at = datetime.now().isoformat(timespec="seconds")
    portable_export = {
        "application": "DeadlineLens",
        "exported_at": generated_at,
        "schema_version": 1,
        "data": snapshot,
    }
    json_bytes = json.dumps(
        portable_export,
        ensure_ascii=False,
        indent=2,
        default=str,
    ).encode("utf-8")

    deadline_rows = []
    for item in deadlines:
        deadline_rows.append(
            {
                "ID": item.get("id"),
                "Title": item.get("title"),
                "Subject": item.get("subject"),
                "Deadline": item.get("deadline"),
                "Status": item.get("status"),
                "Difficulty": item.get("difficulty"),
                "Risk score": item.get("risk_score"),
                "Description": item.get("description"),
            }
        )
    deadline_csv = pd.DataFrame(deadline_rows).to_csv(
        index=False
    ).encode("utf-8-sig")

    database_bytes = get_database_file_bytes()
    date_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    st.subheader("Download backups")
    db_col, json_col, csv_col = st.columns(3)
    with db_col:
        st.download_button(
            "🗄️ Full database backup",
            data=database_bytes,
            file_name=f"DeadlineLens_backup_{date_stamp}.db",
            mime="application/x-sqlite3",
            disabled=not bool(database_bytes),
            width="stretch",
        )
        st.caption("Best for restoring the complete application data.")
    with json_col:
        st.download_button(
            "📦 Portable JSON export",
            data=json_bytes,
            file_name=f"DeadlineLens_export_{date_stamp}.json",
            mime="application/json",
            width="stretch",
        )
        st.caption("Human-readable export containing all major tables.")
    with csv_col:
        st.download_button(
            "📊 Deadlines CSV",
            data=deadline_csv,
            file_name=f"DeadlineLens_deadlines_{date_stamp}.csv",
            mime="text/csv",
            width="stretch",
        )
        st.caption("Convenient for Excel, Sheets, and project reports.")

    st.subheader("Backup guidance")
    st.info(
        "Create a full database backup before replacing project files, "
        "moving to another computer, or making major database changes."
    )
    with st.expander("What each file contains"):
        st.markdown(
            """
            - **Database backup (.db):** complete SQLite data, including IDs and relationships.
            - **Portable JSON (.json):** deadlines, reminders, study tasks, sessions, and goals.
            - **Deadlines CSV (.csv):** a simple spreadsheet-friendly deadline list.
            """
        )



def show_restore_center() -> None:
    """Validate and restore a complete DeadlineLens SQLite backup."""
    st.header("♻️ Data Restore — Phase 14")
    st.caption(
        "Restore a full .db backup created from the Backup & Export page. "
        "DeadlineLens validates the file and preserves the current database "
        "as a recovery copy before replacement."
    )

    st.warning(
        "Restoring replaces the current deadlines, study plans, sessions, "
        "goals, and reminder history. Download a fresh backup first."
    )

    uploaded_backup = st.file_uploader(
        "Choose a DeadlineLens database backup",
        type=["db", "sqlite", "sqlite3"],
        key="restore_database_upload",
    )

    if uploaded_backup is None:
        st.info("Upload a .db backup to preview its contents safely.")
        return

    database_bytes = uploaded_backup.getvalue()

    try:
        backup_info = inspect_database_backup(database_bytes)
    except ValueError as error:
        st.error(str(error))
        return
    except Exception as error:
        st.error("The backup could not be inspected.")
        st.exception(error)
        return

    st.success("Compatible DeadlineLens backup detected.")
    counts = backup_info["counts"]
    metric_one, metric_two, metric_three, metric_four = st.columns(4)
    metric_one.metric("Deadlines", counts.get("deadlines", 0))
    metric_two.metric("Study tasks", counts.get("study_tasks", 0))
    metric_three.metric("Study sessions", counts.get("study_sessions", 0))
    metric_four.metric(
        "Reminder records",
        counts.get("reminder_history", 0),
    )

    with st.expander("Backup details"):
        st.write("Filename:", uploaded_backup.name)
        st.write("Size:", f"{len(database_bytes) / 1024:.1f} KB")
        st.write(
            "Detected tables:",
            ", ".join(backup_info.get("tables", [])),
        )

    confirmation = st.text_input(
        'Type RESTORE to enable the restore button',
        key="restore_confirmation",
    )
    restore_clicked = st.button(
        "♻️ Restore this backup",
        type="primary",
        disabled=confirmation.strip().upper() != "RESTORE",
        width="stretch",
    )

    if restore_clicked:
        try:
            with st.spinner("Validating and restoring your data..."):
                recovery_filename = restore_database_backup(database_bytes)
            st.success(
                "Restore completed successfully. The previous database was "
                f"saved as {recovery_filename}."
            )
            st.info("Reloading DeadlineLens with the restored data...")
            st.rerun()
        except Exception as error:
            st.error(
                "Restore failed. Your previous database was kept or "
                "automatically recovered."
            )
            st.exception(error)


def show_settings_page() -> None:
    """Manage persistent DeadlineLens preferences."""
    st.markdown(
        """
        <div class="dl-page-header">
            <h1>⚙️ Settings</h1>
            <p>Personalize your dashboard, timetable defaults, study planning, and reminders.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    current = load_app_settings()

    with st.form("deadline_lens_settings_form"):
        st.subheader("👤 Profile")
        student_name = st.text_input(
            "Student name",
            value=str(current.get("student_name", "")),
            placeholder="Enter your name",
        )
        show_welcome_name = st.checkbox(
            "Show my name in the dashboard greeting",
            value=bool(current.get("show_welcome_name", True)),
        )

        st.subheader("🎓 Academic defaults")
        left, right = st.columns(2)
        with left:
            program_options = ["MCA", "MBA", "All"]
            current_program = str(current.get("default_program", "MCA"))
            program_index = program_options.index(current_program) if current_program in program_options else 0
            default_program = st.selectbox(
                "Default timetable program",
                program_options,
                index=program_index,
            )
        with right:
            default_study_hours = st.number_input(
                "Default study hours per day",
                min_value=0.5,
                max_value=8.0,
                value=float(current.get("default_study_hours", 2.0)),
                step=0.5,
            )

        st.subheader("🔔 Planning & reminders")
        first, second = st.columns(2)
        with first:
            daily_goal_minutes = st.number_input(
                "Preferred daily study goal (minutes)",
                min_value=15,
                max_value=720,
                value=int(current.get("daily_goal_minutes", 120)),
                step=15,
            )
        with second:
            reminder_days_before = st.number_input(
                "Default reminder lead time (days)",
                min_value=0,
                max_value=30,
                value=int(current.get("reminder_days_before", 2)),
                step=1,
            )

        saved = st.form_submit_button(
            "💾 Save settings",
            type="primary",
            width="stretch",
        )

    if saved:
        updated = {
            "student_name": student_name.strip(),
            "default_program": default_program,
            "default_study_hours": float(default_study_hours),
            "daily_goal_minutes": int(daily_goal_minutes),
            "reminder_days_before": int(reminder_days_before),
            "show_welcome_name": bool(show_welcome_name),
        }
        try:
            save_app_settings(updated)
            st.success("Settings saved successfully.")
        except OSError as error:
            st.error("Settings could not be saved.")
            st.exception(error)

    st.info(
        "These preferences are stored locally in database/app_settings.json and are included when you copy the project folder."
    )


def show_help_about_page() -> None:
    """Show the built-in user guide, project information, and health check."""
    st.markdown(
        """
        <div class="dl-page-hero">
            <span class="dl-eyebrow">DeadlineLens v2.0</span>
            <h1>❓ Help & About</h1>
            <p>Learn the complete workflow, check the application status, and prepare a smooth project demonstration.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    guide_tab, health_tab, about_tab = st.tabs(
        ["📘 User Guide", "🩺 System Health", "ℹ️ About"]
    )

    with guide_tab:
        st.subheader("Quick Start")
        steps = [
            ("1", "Upload a notice", "Open Upload Notice and choose an image of an academic notice or timetable."),
            ("2", "Review OCR results", "Check the extracted title, subject, date, and timetable rows before saving."),
            ("3", "Save deadlines", "Select the required examinations and save them to the DeadlineLens database."),
            ("4", "Plan your study", "Open Study Planner, generate a plan, and mark tasks complete as you study."),
            ("5", "Track and export", "Use Calendar, Analytics, Mock Tests, Backup, and Export for ongoing progress."),
        ]
        for number, title, description in steps:
            st.markdown(
                f"""
                <div class="dl-guide-step">
                    <div class="dl-step-number">{number}</div>
                    <div><strong>{title}</strong><br><span>{description}</span></div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.subheader("Recommended Demo Flow")
        st.info(
            "Upload Notice → OCR Preview → Save Exams → Dashboard → Calendar → "
            "Study Planner → Analytics → Backup & Export"
        )

        with st.expander("Common troubleshooting"):
            st.markdown(
                """
                **The timetable is not detected:** Use a clear, straight image with readable dates and course codes.

                **The app does not show a recent code change:** Stop Streamlit with `Ctrl + C`, then run `streamlit run app.py` again.

                **A deadline is skipped:** It may already exist in the database as a duplicate.

                **Google Calendar or email fails:** Check the related credentials and internet connection.

                **Before replacing the project folder:** Download a database backup from **Backup & Export**.
                """
            )

    with health_tab:
        st.subheader("Application Health Check")
        checks: list[tuple[str, bool, str]] = []

        try:
            deadlines = get_all_deadlines()
            checks.append(("SQLite database", True, f"Connected · {len(deadlines)} deadline(s)"))
        except Exception as error:
            checks.append(("SQLite database", False, str(error)))
            deadlines = []

        project_root = Path(__file__).resolve().parent
        checks.append(("OCR service", (project_root / "services" / "ocr_service.py").exists(), "OCR module available"))
        checks.append(("Timetable parser", (project_root / "services" / "timetable_parser.py").exists(), "Parser module available"))
        checks.append(("UI stylesheet", (project_root / "assets" / "style.css").exists(), "Custom theme loaded"))
        checks.append(("Database backup tools", callable(get_database_file_bytes), "Backup and restore functions available"))

        passed = sum(1 for _, status, _ in checks if status)
        total = len(checks)
        first, second, third = st.columns(3)
        first.metric("Checks passed", f"{passed}/{total}")
        second.metric("Saved deadlines", len(deadlines))
        database_path = project_root / "database" / "deadlines.db"
        database_size = database_path.stat().st_size / 1024 if database_path.exists() else 0
        third.metric("Database size", f"{database_size:.1f} KB")

        for name, status, detail in checks:
            icon = "✅" if status else "❌"
            st.markdown(
                f"""
                <div class="dl-health-row">
                    <span class="dl-health-icon">{icon}</span>
                    <div><strong>{name}</strong><br><span>{html.escape(detail)}</span></div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        if passed == total:
            st.success("All core DeadlineLens components are ready.")
        else:
            st.warning("One or more checks need attention before your project demonstration.")

    with about_tab:
        st.markdown(
            """
            ### 🎓 DeadlineLens
            **AI-Powered Academic Deadline Manager**

            DeadlineLens converts academic notices and examination timetables into structured deadlines using OCR. It combines deadline tracking, risk analysis, reminders, calendar tools, study planning, performance insights, mock-test tracking, and data backup in one application.

            **Core technologies**

            Python · Streamlit · SQLite · EasyOCR/Tesseract · OpenCV · Plotly · Google Calendar · ReportLab

            **Version:** 2.0 Release Candidate  
            **Academic year:** 2026
            """
        )

        st.subheader("Major Modules")
        modules = [
            "OCR Notice Processing",
            "Timetable Parser",
            "Deadline Dashboard",
            "Calendar & Reminders",
            "Smart Study Planner",
            "Analytics & Readiness",
            "Mock Test Tracker",
            "Backup, Restore & Export",
        ]
        columns = st.columns(2)
        for index, module in enumerate(modules):
            columns[index % 2].markdown(f"- ✅ {module}")

# Apply programmatic navigation before the radio widget is created.
if "requested_nav_page" in st.session_state:
    st.session_state["nav_page"] = st.session_state.pop(
        "requested_nav_page"
    )

with st.sidebar:
    st.markdown(
        """
        <div class="dl-brand">
            <div class="dl-brand-mark">🎓</div>
            <h2>DeadlineLens</h2>
            <p>AI Academic Assistant</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    page = st.radio(
        "Navigation",
        [
            "Dashboard",
            "Upload Notice",
            "Saved Deadlines",
            "Calendar",
            "Study Planner",
            "Email Reminders",
            "Reminder History",
            "Analytics",
            "Exam Resources",
            "Mock Test Tracker",
            "Backup & Export",
            "Restore Data",
            "Settings",
            "Help & About",
            "🩺 System Health",
        ],
        key="nav_page",
    )

    st.markdown("---")
    st.success("🟢 System Ready")
    st.caption("DeadlineLens v2.0")

if page == "Dashboard":
    show_reminder_center()
    show_dashboard()
elif page == "Upload Notice":
    show_upload_page()
elif page == "Saved Deadlines":
    show_saved_deadlines()
elif page == "Calendar":
    show_calendar_page()
elif page == "Study Planner":
    show_study_planner()
elif page == "Email Reminders":
    show_email_reminder_test()
elif page == "Reminder History":
    show_reminder_history()
elif page == "Analytics":
    show_analytics_charts()
elif page == "Exam Resources":
    show_exam_resources()
elif page == "Mock Test Tracker":
    show_mock_test_tracker()
elif page == "Backup & Export":
    show_backup_center()
elif page == "Restore Data":
    show_restore_center()
elif page == "Settings":
    show_settings_page()
elif page == "Help & About":
    show_help_about_page()
elif page == "🩺 System Health":
    show_system_health()

show_app_footer()

