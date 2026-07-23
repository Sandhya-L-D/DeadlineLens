from datetime import datetime
import json
from pathlib import Path


LOG_FILE = Path("database/activity_log.json")


def log_activity(action: str) -> None:
    """
    Save one activity message.
    """

    LOG_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    activities = []

    if LOG_FILE.exists():
        try:
            with LOG_FILE.open(
                "r",
                encoding="utf-8",
            ) as file:
                activities = json.load(file)
        except (json.JSONDecodeError, OSError):
            activities = []

    activities.append(
        {
            "time": datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "action": action,
        }
    )

    activities = activities[-200:]

    with LOG_FILE.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            activities,
            file,
            indent=4,
        )


def get_activity_log() -> list[dict]:
    """
    Return saved activities.
    """

    if not LOG_FILE.exists():
        return []

    try:
        with LOG_FILE.open(
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

        if isinstance(data, list):
            return data

    except (json.JSONDecodeError, OSError):
        pass

    return []