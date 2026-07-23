from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


BASE_DIR = Path(__file__).resolve().parent.parent

CREDENTIALS_FILE = BASE_DIR / "credentials.json"
TOKEN_FILE = BASE_DIR / "token.json"

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events"
]


def get_calendar_service():
    """
    Authenticate the user and return a Google Calendar service.

    On the first run, the browser opens and asks the user
    to sign in and allow Calendar access.
    """

    credentials = None

    if TOKEN_FILE.exists():
        credentials = Credentials.from_authorized_user_file(
            str(TOKEN_FILE),
            SCOPES,
        )

    if not credentials or not credentials.valid:
        if (
            credentials
            and credentials.expired
            and credentials.refresh_token
        ):
            credentials.refresh(Request())

        else:
            if not CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    "credentials.json was not found in the "
                    "DeadlineLens project folder."
                )

            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE),
                SCOPES,
            )

            credentials = flow.run_local_server(
                port=0,
            )

        TOKEN_FILE.write_text(
            credentials.to_json(),
            encoding="utf-8",
        )

    return build(
        "calendar",
        "v3",
        credentials=credentials,
    )


def create_calendar_event(
    title: str,
    start_datetime: datetime,
    description: str = "",
    duration_hours: int = 3,
    timezone: str = "Asia/Kolkata",
) -> dict[str, Any]:
    """
    Create one event in the user's primary Google Calendar.
    """

    service = get_calendar_service()

    end_datetime = start_datetime + timedelta(
        hours=duration_hours
    )

    event_body = {
        "summary": title,
        "description": description,
        "start": {
            "dateTime": start_datetime.isoformat(),
            "timeZone": timezone,
        },
        "end": {
            "dateTime": end_datetime.isoformat(),
            "timeZone": timezone,
        },
        "reminders": {
            "useDefault": False,
            "overrides": [
                {
                    "method": "popup",
                    "minutes": 24 * 60,
                },
                {
                    "method": "popup",
                    "minutes": 2 * 60,
                },
            ],
        },
    }

    try:
        created_event = (
            service.events()
            .insert(
                calendarId="primary",
                body=event_body,
            )
            .execute()
        )

        return created_event

    except HttpError as error:
        raise RuntimeError(
            f"Google Calendar API error: {error}"
        ) from error


def create_multiple_calendar_events(
    events: list[dict[str, Any]],
) -> tuple[int, list[str]]:
    """
    Create multiple Google Calendar events.

    Returns:
        success_count
        failed event titles
    """

    success_count = 0
    failed_events = []

    service = get_calendar_service()

    for event in events:
        start_datetime = event["deadline"]

        end_datetime = start_datetime + timedelta(
            hours=3
        )

        event_body = {
            "summary": event["title"],
            "description": event.get(
                "description",
                "",
            ),
            "start": {
                "dateTime": start_datetime.isoformat(),
                "timeZone": "Asia/Kolkata",
            },
            "end": {
                "dateTime": end_datetime.isoformat(),
                "timeZone": "Asia/Kolkata",
            },
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {
                        "method": "popup",
                        "minutes": 1440,
                    },
                    {
                        "method": "popup",
                        "minutes": 120,
                    },
                ],
            },
        }

        try:
            (
                service.events()
                .insert(
                    calendarId="primary",
                    body=event_body,
                )
                .execute()
            )

            success_count += 1

        except HttpError:
            failed_events.append(
                event["title"]
            )

    return success_count, failed_events