from datetime import date, timedelta
import sqlite3
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "deadlines.db"


def get_connection() -> sqlite3.Connection:
    """
    Create and return a database connection.

    Database rows can be accessed using column names.
    """
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row

    return connection
def reminder_was_sent(
    deadline_id: int,
    recipient_email: str,
    reminder_type: str,
) -> bool:
    """Check whether a specific reminder was already sent."""

    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT id
            FROM reminder_history
            WHERE deadline_id = ?
              AND recipient_email = ?
              AND reminder_type = ?
            LIMIT 1
            """,
            (
                deadline_id,
                recipient_email.strip().lower(),
                reminder_type,
            ),
        ).fetchone()

    return row is not None


def mark_reminder_as_sent(
    deadline_id: int,
    recipient_email: str,
    reminder_type: str,
) -> bool:
    """Record a reminder after it was sent successfully."""

    try:
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO reminder_history (
                    deadline_id,
                    recipient_email,
                    reminder_type
                )
                VALUES (?, ?, ?)
                """,
                (
                    deadline_id,
                    recipient_email.strip().lower(),
                    reminder_type,
                ),
            )
            connection.commit()

        return True

    except sqlite3.IntegrityError:
        return False


def create_reminder_history_table() -> None:
    """Create the reminder history table."""

    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS reminder_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deadline_id INTEGER NOT NULL,
                recipient_email TEXT NOT NULL,
                reminder_type TEXT NOT NULL,
                sent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(
                    deadline_id,
                    recipient_email,
                    reminder_type
                )
            )
            """
        )
        connection.commit()
def get_reminder_history() -> list[dict[str, Any]]:
    """
    Return all sent reminder records,
    newest reminders first.
    """
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                reminder_history.id,
                reminder_history.deadline_id,
                reminder_history.recipient_email,
                reminder_history.reminder_type,
                reminder_history.sent_at,
                deadlines.title,
                deadlines.subject,
                deadlines.deadline
            FROM reminder_history
            LEFT JOIN deadlines
                ON deadlines.id = reminder_history.deadline_id
            ORDER BY reminder_history.sent_at DESC
            """
        ).fetchall()

    return [dict(row) for row in rows]

def create_deadlines_table() -> None:
    """
    Create the deadlines table when it does not already exist.
    """
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS deadlines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                subject TEXT,
                description TEXT,
                deadline TEXT NOT NULL,
                difficulty TEXT NOT NULL DEFAULT 'Medium',
                status TEXT NOT NULL DEFAULT 'Not Started',
                risk_score INTEGER NOT NULL DEFAULT 0,
                source_text TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(title, deadline)
            )
            """
        )
        connection.execute(
        """
        CREATE TABLE IF NOT EXISTS reminder_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        deadline_id INTEGER NOT NULL,
        recipient_email TEXT NOT NULL,
        reminder_type TEXT NOT NULL,
        sent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (deadline_id)
            REFERENCES deadlines(id)
            ON DELETE CASCADE
         )
        """
        )
        connection.commit()


def create_reminder_history_table() -> None:
    """
    Store reminders that were already sent.

    This prevents the same automatic reminder from being
    sent repeatedly whenever Streamlit reruns.
    """
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS reminder_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deadline_id INTEGER NOT NULL,
                recipient_email TEXT NOT NULL,
                reminder_type TEXT NOT NULL,
                sent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                UNIQUE(
                    deadline_id,
                    recipient_email,
                    reminder_type
                ),

                FOREIGN KEY(deadline_id)
                    REFERENCES deadlines(id)
                    ON DELETE CASCADE
            )
            """
        )

        connection.commit()


def add_deadline(
    title: str,
    subject: str,
    description: str,
    deadline: str,
    difficulty: str,
    risk_score: int,
    source_text: str,
) -> bool:
    """
    Insert a new deadline.

    Returns:
        True when saved successfully.
        False when the same title and deadline already exist.
    """
    try:
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO deadlines (
                    title,
                    subject,
                    description,
                    deadline,
                    difficulty,
                    status,
                    risk_score,
                    source_text
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    title,
                    subject,
                    description,
                    deadline,
                    difficulty,
                    "Not Started",
                    risk_score,
                    source_text,
                ),
            )

            connection.commit()

        return True

    except sqlite3.IntegrityError:
        return False


def get_all_deadlines() -> list[dict[str, Any]]:
    """
    Return all deadlines ordered by nearest deadline first.
    """
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                id,
                title,
                subject,
                description,
                deadline,
                difficulty,
                status,
                risk_score,
                source_text,
                created_at
            FROM deadlines
            ORDER BY deadline ASC
            """
        ).fetchall()

    return [dict(row) for row in rows]


def update_deadline_status(
    deadline_id: int,
    status: str,
) -> None:
    """
    Update the completion status of a deadline.
    """
    allowed_statuses = {
        "Not Started",
        "In Progress",
        "Completed",
    }

    if status not in allowed_statuses:
        raise ValueError("Invalid deadline status.")

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE deadlines
            SET status = ?
            WHERE id = ?
            """,
            (
                status,
                deadline_id,
            ),
        )

        connection.commit()


def delete_deadline(deadline_id: int) -> None:
    """
    Delete one deadline and its reminder history.
    """
    with get_connection() as connection:
        connection.execute(
            """
            DELETE FROM reminder_history
            WHERE deadline_id = ?
            """,
            (deadline_id,),
        )

        connection.execute(
            """
            DELETE FROM deadlines
            WHERE id = ?
            """,
            (deadline_id,),
        )

        connection.commit()


def reminder_was_sent(
    deadline_id: int,
    recipient_email: str,
    reminder_type: str,
) -> bool:
    """
    Check whether a specific reminder was already sent.
    """
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT id
            FROM reminder_history
            WHERE deadline_id = ?
              AND recipient_email = ?
              AND reminder_type = ?
            LIMIT 1
            """,
            (
                deadline_id,
                recipient_email.strip().lower(),
                reminder_type,
            ),
        ).fetchone()

    return row is not None


def mark_reminder_as_sent(
    deadline_id: int,
    recipient_email: str,
    reminder_type: str,
) -> bool:
    """
    Record a successfully sent reminder.

    Returns:
        True when the history record was created.
        False when the same reminder was already recorded.
    """
    try:
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO reminder_history (
                    deadline_id,
                    recipient_email,
                    reminder_type
                )
                VALUES (?, ?, ?)
                """,
                (
                    deadline_id,
                    recipient_email.strip().lower(),
                    reminder_type,
                ),
            )

            connection.commit()

        return True

    except sqlite3.IntegrityError:
        return False


def get_reminder_history() -> list[dict[str, Any]]:
    """
    Return reminder history with deadline information.
    """
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                reminder_history.id,
                reminder_history.deadline_id,
                reminder_history.recipient_email,
                reminder_history.reminder_type,
                reminder_history.sent_at,
                deadlines.title,
                deadlines.deadline
            FROM reminder_history
            INNER JOIN deadlines
                ON deadlines.id = reminder_history.deadline_id
            ORDER BY reminder_history.sent_at DESC
            """
        ).fetchall()

    return [dict(row) for row in rows]


def create_study_tasks_table() -> None:
    """Create persistent study-plan tasks for saved examinations."""
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS study_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deadline_id INTEGER NOT NULL,
                task_date TEXT NOT NULL,
                task TEXT NOT NULL,
                stage TEXT NOT NULL,
                hours REAL NOT NULL DEFAULT 1.0,
                completed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(deadline_id, task_date, task),
                FOREIGN KEY(deadline_id) REFERENCES deadlines(id) ON DELETE CASCADE
            )
            """
        )
        connection.commit()


def replace_study_plan(
    deadline_id: int,
    schedule: list[dict[str, Any]],
) -> int:
    """Replace an examination's saved plan and return tasks saved."""
    with get_connection() as connection:
        connection.execute(
            "DELETE FROM study_tasks WHERE deadline_id = ?",
            (deadline_id,),
        )

        rows = [
            (
                deadline_id,
                item["date"].isoformat(),
                str(item["task"]),
                str(item["stage"]),
                float(item["hours"]),
                0,
            )
            for item in schedule
        ]

        connection.executemany(
            """
            INSERT INTO study_tasks (
                deadline_id, task_date, task, stage, hours, completed
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        connection.commit()

    return len(rows)


def get_study_tasks(deadline_id: int) -> list[dict[str, Any]]:
    """Return all saved study tasks for one examination."""
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, deadline_id, task_date, task, stage, hours, completed
            FROM study_tasks
            WHERE deadline_id = ?
            ORDER BY task_date ASC, id ASC
            """,
            (deadline_id,),
        ).fetchall()

    return [dict(row) for row in rows]


def update_study_task_completion(task_id: int, completed: bool) -> None:
    """Mark one study task complete or incomplete."""
    with get_connection() as connection:
        connection.execute(
            "UPDATE study_tasks SET completed = ? WHERE id = ?",
            (1 if completed else 0, task_id),
        )
        connection.commit()


def rebalance_study_plan(
    deadline_id: int,
    start_date: date,
    exam_date: date,
) -> int:
    """Redistribute unfinished tasks across remaining days before an exam."""
    available_days = (exam_date - start_date).days

    if available_days <= 0:
        return 0

    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id
            FROM study_tasks
            WHERE deadline_id = ? AND completed = 0
            ORDER BY task_date ASC, id ASC
            """,
            (deadline_id,),
        ).fetchall()

        if not rows:
            return 0

        task_ids = [int(row["id"]) for row in rows]
        study_dates = [
            start_date + timedelta(days=offset)
            for offset in range(available_days)
        ]

        updates = []
        for index, task_id in enumerate(task_ids):
            target_date = study_dates[index % len(study_dates)]
            updates.append((target_date.isoformat(), task_id))

        connection.executemany(
            "UPDATE study_tasks SET task_date = ? WHERE id = ?",
            updates,
        )
        connection.commit()

    return len(task_ids)


def delete_study_plan(deadline_id: int) -> None:
    """Delete the saved study plan for one examination."""
    with get_connection() as connection:
        connection.execute(
            "DELETE FROM study_tasks WHERE deadline_id = ?",
            (deadline_id,),
        )
        connection.commit()


def create_study_sessions_table() -> None:
    """Create a table for recording actual study sessions."""
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS study_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deadline_id INTEGER NOT NULL,
                session_date TEXT NOT NULL,
                topic TEXT NOT NULL,
                minutes INTEGER NOT NULL,
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(deadline_id) REFERENCES deadlines(id) ON DELETE CASCADE
            )
            """
        )
        connection.commit()


def add_study_session(
    deadline_id: int,
    session_date: date,
    topic: str,
    minutes: int,
    notes: str = "",
) -> int:
    """Save one completed study session and return its database id."""
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO study_sessions (
                deadline_id, session_date, topic, minutes, notes
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                deadline_id,
                session_date.isoformat(),
                topic.strip(),
                int(minutes),
                notes.strip(),
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)


def get_study_sessions(deadline_id: int) -> list[dict[str, Any]]:
    """Return recorded study sessions for one examination."""
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, deadline_id, session_date, topic, minutes, notes, created_at
            FROM study_sessions
            WHERE deadline_id = ?
            ORDER BY session_date DESC, id DESC
            """,
            (deadline_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def delete_study_session(session_id: int) -> None:
    """Delete one recorded study session."""
    with get_connection() as connection:
        connection.execute(
            "DELETE FROM study_sessions WHERE id = ?",
            (session_id,),
        )
        connection.commit()


def create_study_goals_table() -> None:
    """Create a table for per-exam daily study targets."""
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS study_goals (
                deadline_id INTEGER PRIMARY KEY,
                target_minutes INTEGER NOT NULL DEFAULT 60,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(deadline_id) REFERENCES deadlines(id) ON DELETE CASCADE
            )
            """
        )
        connection.commit()


def set_study_goal(deadline_id: int, target_minutes: int) -> None:
    """Create or update the daily study target for one examination."""
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO study_goals (deadline_id, target_minutes, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(deadline_id) DO UPDATE SET
                target_minutes = excluded.target_minutes,
                updated_at = CURRENT_TIMESTAMP
            """,
            (deadline_id, int(target_minutes)),
        )
        connection.commit()


def get_study_goal(deadline_id: int, default_minutes: int = 60) -> int:
    """Return the saved daily study target for one examination."""
    with get_connection() as connection:
        row = connection.execute(
            "SELECT target_minutes FROM study_goals WHERE deadline_id = ?",
            (deadline_id,),
        ).fetchone()
    if row is None:
        return int(default_minutes)
    return int(row["target_minutes"])



def create_exam_resources_table() -> None:
    """Create a table for exam notes, links, and study resources."""
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS exam_resources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deadline_id INTEGER NOT NULL,
                resource_type TEXT NOT NULL DEFAULT 'Note',
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(deadline_id) REFERENCES deadlines(id) ON DELETE CASCADE
            )
            """
        )
        connection.commit()


def add_exam_resource(
    deadline_id: int,
    resource_type: str,
    title: str,
    content: str,
) -> int:
    """Save one note, link, or study resource and return its ID."""
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO exam_resources (
                deadline_id, resource_type, title, content
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                int(deadline_id),
                resource_type.strip() or 'Note',
                title.strip(),
                content.strip(),
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)


def get_exam_resources(deadline_id: int) -> list[dict[str, Any]]:
    """Return saved resources for one examination, newest first."""
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM exam_resources
            WHERE deadline_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (int(deadline_id),),
        ).fetchall()
    return [dict(row) for row in rows]


def delete_exam_resource(resource_id: int) -> None:
    """Delete one exam resource."""
    with get_connection() as connection:
        connection.execute(
            "DELETE FROM exam_resources WHERE id = ?",
            (int(resource_id),),
        )
        connection.commit()

create_deadlines_table()
create_reminder_history_table()

def export_database_snapshot() -> dict[str, list[dict[str, Any]]]:
    """Return a JSON-serializable snapshot of all DeadlineLens tables."""
    table_names = [
        "deadlines",
        "reminder_history",
        "study_tasks",
        "study_sessions",
        "study_goals",
        "exam_resources",
        "mock_tests",
    ]
    snapshot: dict[str, list[dict[str, Any]]] = {}

    with get_connection() as connection:
        existing_tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

        for table_name in table_names:
            if table_name not in existing_tables:
                snapshot[table_name] = []
                continue
            rows = connection.execute(
                f"SELECT * FROM {table_name}"
            ).fetchall()
            snapshot[table_name] = [dict(row) for row in rows]

    return snapshot


def get_database_file_bytes() -> bytes:
    """Return the current SQLite database as raw bytes for backup."""
    if not DATABASE_PATH.exists():
        return b""
    return DATABASE_PATH.read_bytes()



def inspect_database_backup(database_bytes: bytes) -> dict[str, Any]:
    """Validate an uploaded SQLite backup and return safe table counts."""
    import tempfile

    if not database_bytes:
        raise ValueError("The uploaded backup is empty.")

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=".db",
            dir=BASE_DIR,
            delete=False,
        ) as temporary_file:
            temporary_file.write(database_bytes)
            temporary_path = Path(temporary_file.name)

        connection = sqlite3.connect(temporary_path)
        connection.row_factory = sqlite3.Row
        try:
            integrity_result = connection.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0]
            if str(integrity_result).lower() != "ok":
                raise ValueError(
                    f"SQLite integrity check failed: {integrity_result}"
                )

            existing_tables = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }

            if "deadlines" not in existing_tables:
                raise ValueError(
                    "This file is not a compatible DeadlineLens backup "
                    "because the deadlines table is missing."
                )

            supported_tables = [
                "deadlines",
                "reminder_history",
                "study_tasks",
                "study_sessions",
                "study_goals",
                "exam_resources",
                "mock_tests",
            ]
            counts: dict[str, int] = {}
            for table_name in supported_tables:
                if table_name in existing_tables:
                    row = connection.execute(
                        f"SELECT COUNT(*) AS total FROM {table_name}"
                    ).fetchone()
                    counts[table_name] = int(row["total"])
                else:
                    counts[table_name] = 0

            return {
                "valid": True,
                "counts": counts,
                "tables": sorted(existing_tables),
            }
        finally:
            connection.close()
    except sqlite3.DatabaseError as error:
        raise ValueError(
            "The uploaded file is not a valid SQLite database."
        ) from error
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink(missing_ok=True)


def restore_database_backup(database_bytes: bytes) -> str:
    """Safely replace the active database and retain a recovery copy."""
    from datetime import datetime
    import os
    import tempfile

    # Validate the complete file before touching the active database.
    inspect_database_backup(database_bytes)

    temporary_path: Path | None = None
    recovery_path = BASE_DIR / (
        "deadlines_before_restore_"
        + datetime.now().strftime("%Y%m%d_%H%M%S")
        + ".db"
    )

    try:
        with tempfile.NamedTemporaryFile(
            suffix=".db",
            dir=BASE_DIR,
            delete=False,
        ) as temporary_file:
            temporary_file.write(database_bytes)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
            temporary_path = Path(temporary_file.name)

        if DATABASE_PATH.exists():
            DATABASE_PATH.replace(recovery_path)

        temporary_path.replace(DATABASE_PATH)
        temporary_path = None
        return recovery_path.name
    except Exception:
        # Put the previous database back when replacement fails.
        if not DATABASE_PATH.exists() and recovery_path.exists():
            recovery_path.replace(DATABASE_PATH)
        raise
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink(missing_ok=True)

def create_mock_tests_table() -> None:
    """Create the mock-test results table."""
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS mock_tests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deadline_id INTEGER NOT NULL,
                test_date TEXT NOT NULL,
                test_name TEXT NOT NULL,
                score REAL NOT NULL,
                total_marks REAL NOT NULL,
                duration_minutes INTEGER NOT NULL DEFAULT 0,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(deadline_id) REFERENCES deadlines(id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_mock_tests_deadline
            ON mock_tests(deadline_id)
            """
        )
        connection.commit()


def add_mock_test(
    deadline_id: int,
    test_date: str,
    test_name: str,
    score: float,
    total_marks: float,
    duration_minutes: int,
    notes: str,
) -> int:
    """Save one mock-test result and return its ID."""
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO mock_tests (
                deadline_id, test_date, test_name, score,
                total_marks, duration_minutes, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(deadline_id),
                test_date,
                test_name.strip(),
                float(score),
                float(total_marks),
                int(duration_minutes),
                notes.strip(),
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)


def get_mock_tests(deadline_id: int) -> list[dict[str, Any]]:
    """Return mock-test results for one examination."""
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM mock_tests
            WHERE deadline_id = ?
            ORDER BY test_date ASC, id ASC
            """,
            (int(deadline_id),),
        ).fetchall()
    return [dict(row) for row in rows]


def delete_mock_test(mock_test_id: int) -> None:
    """Delete one mock-test result."""
    with get_connection() as connection:
        connection.execute(
            "DELETE FROM mock_tests WHERE id = ?",
            (int(mock_test_id),),
        )
        connection.commit()

def create_database_indexes() -> None:
    """
    Create indexes that improve deadline, reminder,
    study-plan, resource, and mock-test queries.
    """

    with get_connection() as connection:
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_deadlines_deadline
            ON deadlines(deadline)
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_deadlines_subject
            ON deadlines(subject)
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_deadlines_status
            ON deadlines(status)
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_reminder_deadline
            ON reminder_history(deadline_id)
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_study_tasks_deadline
            ON study_tasks(deadline_id)
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_study_tasks_date
            ON study_tasks(task_date)
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_study_sessions_deadline
            ON study_sessions(deadline_id)
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_exam_resources_deadline
            ON exam_resources(deadline_id)
            """
        )

        connection.commit()

create_study_tasks_table()
create_study_sessions_table()
create_study_goals_table()
create_exam_resources_table()
create_mock_tests_table()
create_database_indexes()