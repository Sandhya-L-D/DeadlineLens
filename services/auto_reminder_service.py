from datetime import datetime
from typing import Any

from database.database import (
    get_all_deadlines,
    mark_reminder_as_sent,
    reminder_was_sent,
)
from services.email_service import send_deadline_email


REMINDER_DAYS = {
    7: "7_days",
    3: "3_days",
    1: "1_day",
    0: "today",
}


def check_and_send_reminders(
    recipient_email: str,
) -> tuple[int, list[str]]:
    """
    Check pending deadlines and send automatic reminders.

    Reminders are sent:
    - 7 days before
    - 3 days before
    - 1 day before
    - On the deadline day

    The reminder history table prevents duplicate emails.

    Returns:
        A tuple containing:
        - Number of reminders sent successfully
        - List of failed deadline titles
    """
    recipient_email = recipient_email.strip().lower()

    if not recipient_email:
        return 0, []

    deadlines = get_all_deadlines()

    sent_count = 0
    failed_titles: list[str] = []

    now = datetime.now()

    for deadline in deadlines:
        if deadline["status"] == "Completed":
            continue

        deadline_datetime = datetime.fromisoformat(
            deadline["deadline"]
        )

        days_remaining = (
            deadline_datetime.date() - now.date()
        ).days

        reminder_type = REMINDER_DAYS.get(days_remaining)

        if reminder_type is None:
            continue

        already_sent = reminder_was_sent(
            deadline_id=deadline["id"],
            recipient_email=recipient_email,
            reminder_type=reminder_type,
        )

        if already_sent:
            continue

        try:
            send_deadline_email(
                recipient=recipient_email,
                title=deadline["title"],
                subject=deadline["subject"],
                deadline_text=deadline_datetime.strftime(
                    "%d %B %Y, %I:%M %p"
                ),
                risk_score=deadline["risk_score"],
            )

            mark_reminder_as_sent(
                deadline_id=deadline["id"],
                recipient_email=recipient_email,
                reminder_type=reminder_type,
            )

            sent_count += 1

        except Exception:
            failed_titles.append(deadline["title"])

    return sent_count, failed_titles