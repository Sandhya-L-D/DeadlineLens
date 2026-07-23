import base64
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


BASE_DIR = Path(__file__).resolve().parent.parent

CREDENTIALS_FILE = BASE_DIR / "credentials.json"
TOKEN_FILE = BASE_DIR / "google_token.json"

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.send",
]


def get_google_credentials() -> Credentials:
    """Authenticate for Google Calendar and Gmail."""

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
                    "credentials.json was not found."
                )

            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE),
                SCOPES,
            )

            credentials = flow.run_local_server(port=0)

        TOKEN_FILE.write_text(
            credentials.to_json(),
            encoding="utf-8",
        )

    return credentials


def send_deadline_email(
    recipient: str,
    title: str,
    subject: str,
    deadline_text: str,
    risk_score: int,
) -> dict[str, Any]:
    """Send one deadline-reminder email."""

    if not recipient.strip():
        raise ValueError("Recipient email is required.")

    credentials = get_google_credentials()

    service = build(
        "gmail",
        "v1",
        credentials=credentials,
    )

    message = EmailMessage()

    message["To"] = recipient.strip()
    message["Subject"] = f"DeadlineLens Reminder: {title}"

    message.set_content(
        f"""
Hello,

This is your DeadlineLens reminder.

Deadline:
{title}

Subject:
{subject or "Not specified"}

Date and time:
{deadline_text}

Risk score:
{risk_score}%

Please plan your preparation accordingly.

Best wishes,
DeadlineLens
""".strip()
    )

    encoded_message = base64.urlsafe_b64encode(
        message.as_bytes()
    ).decode("utf-8")

    try:
        return (
            service.users()
            .messages()
            .send(
                userId="me",
                body={"raw": encoded_message},
            )
            .execute()
        )

    except HttpError as error:
        raise RuntimeError(
            f"Gmail API error: {error}"
        ) from error