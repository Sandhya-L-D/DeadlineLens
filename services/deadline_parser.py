import re
from datetime import datetime
from typing import Optional

import dateparser
from dateparser.search import search_dates


TASK_KEYWORDS = [
    "submit",
    "submission",
    "assignment",
    "complete",
    "record",
    "project",
    "exam",
    "test",
    "presentation",
]


def extract_deadline(text: str) -> Optional[datetime]:
    """Find the most likely future date inside extracted text."""

    results = search_dates(
        text,
        settings={
            "PREFER_DATES_FROM": "future",
            "RETURN_AS_TIMEZONE_AWARE": False,
        },
    )

    if not results:
        return None

    now = datetime.now()
    future_dates = [date for _, date in results if date >= now]

    return min(future_dates) if future_dates else None


def generate_title(text: str) -> str:
    """Generate a simple assignment title from the notice text."""

    lines = [
        line.strip()
        for line in text.splitlines()
        if len(line.strip()) > 3
    ]

    for line in lines:
        lowercase_line = line.lower()

        if any(keyword in lowercase_line for keyword in TASK_KEYWORDS):
            cleaned = re.sub(
                r"\b(by|before|on)\b.*$",
                "",
                line,
                flags=re.IGNORECASE,
            )
            return cleaned.strip()[:100]

    return lines[0][:100] if lines else "New academic deadline"