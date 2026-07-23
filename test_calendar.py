from datetime import datetime, timedelta

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


SCOPES = [
    "https://www.googleapis.com/auth/calendar.events"
]


def get_credentials():
    credentials = None

    try:
        credentials = Credentials.from_authorized_user_file(
            "token.json",
            SCOPES,
        )
    except FileNotFoundError:
        pass

    if not credentials or not credentials.valid:
        if (
            credentials
            and credentials.expired
            and credentials.refresh_token
        ):
            credentials.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json",
                SCOPES,
            )

            credentials = flow.run_local_server(port=0)

        with open("token.json", "w", encoding="utf-8") as token:
            token.write(credentials.to_json())

    return credentials


credentials = get_credentials()

service = build(
    "calendar",
    "v3",
    credentials=credentials,
)

start_time = datetime.now() + timedelta(hours=1)
end_time = start_time + timedelta(hours=1)

event = {
    "summary": "DeadlineLens Test Event",
    "description": "Testing Google Calendar integration.",
    "start": {
        "dateTime": start_time.isoformat(),
        "timeZone": "Asia/Kolkata",
    },
    "end": {
        "dateTime": end_time.isoformat(),
        "timeZone": "Asia/Kolkata",
    },
}

created_event = (
    service.events()
    .insert(
        calendarId="primary",
        body=event,
    )
    .execute()
)

print("Calendar event created successfully!")
print(created_event.get("htmlLink"))