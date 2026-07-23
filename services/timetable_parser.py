import re
from datetime import datetime
from typing import Any


DATE_PATTERN = re.compile(
    r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b"
)

COURSE_CODE_PATTERN = re.compile(
    r"\b[A-Z]{5}\d{3}\b",
    re.IGNORECASE,
)

def is_timetable(text: str) -> bool:
    """
    Return True when the OCR text appears to be an examination timetable.
    """

    keywords = [
        "timetable",
        "time table",
        "examination",
        "course code",
        "theory examination",
        "practical examination",
    ]

    lowered_text = text.lower()

    match_count = sum(
        keyword in lowered_text
        for keyword in keywords
    )

    return match_count >= 2


def normalize_course_code(code: str) -> str:
    """
    Remove spaces and OCR punctuation from a course code.
    """

    cleaned_code = re.sub(
        r"[^A-Za-z0-9]",
        "",
        code,
    )

    return cleaned_code.upper()


def is_valid_course_code(course_code: str) -> bool:
    """
    Check whether a detected value looks like a real course code.
    """

    ignored_values = {
        "DATE",
        "TIME",
        "MBA",
        "MCA",
        "SEM",
        "THEORY",
        "PRACTICAL",
        "COURSE",
        "CODE",
        "EXAMINATION",
        "PROGRAMME",
        "PROGRAM",
        "SUBJECT",
        "NOTIFICATION",
    }

    if not course_code:
        return False

    if course_code in ignored_values:
        return False

    if not any(
        character.isalpha()
        for character in course_code
    ):
        return False

    if not any(
        character.isdigit()
        for character in course_code
    ):
        return False

    if not 6 <= len(course_code) <= 10:
        return False

    if not course_code[-3:].isdigit():
        return False

    return True


def extract_course_codes(text: str) -> list[str]:
    """
    Extract unique valid course codes from text.
    """

    normalized_text = re.sub(
    r"\b([A-Z]{2,7})\s+([A-Z0-9]{1,7}\d{3})\b",
    r"\1\2",
    text,
    flags=re.IGNORECASE,
)

    raw_codes = COURSE_CODE_PATTERN.findall(
        normalized_text
    )

    course_codes: list[str] = []

    for raw_code in raw_codes:
        course_code = normalize_course_code(
            raw_code
        )
       
        if not re.fullmatch(
        r"[A-Z]{2,4}(?:BA|CA)\d{3}",
        course_code,
         ):
            continue

        if not is_valid_course_code(course_code):
            continue

        if course_code not in course_codes:
            course_codes.append(course_code)

    return course_codes

def extract_theory_exam_events(
    text: str,
    default_hour: int,
    default_minute: int,
) -> list[dict[str, Any]]:
    """
    Extract theory examination events.

    Each date owns all course codes until the next date.
    Parsing stops when the practical examination section begins.
    """

    events: list[dict[str, Any]] = []
    seen_events: set[tuple[str, str]] = set()

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    current_datetime: datetime | None = None
    current_lines: list[str] = []

    def process_current_block() -> None:
        if current_datetime is None:
            return

        combined_text = " ".join(current_lines)

        course_codes = extract_course_codes(
            combined_text
        )

        for course_code in course_codes:
            event_key = (
                course_code,
                current_datetime.isoformat(),
            )

            if event_key in seen_events:
                continue

            seen_events.add(event_key)

            events.append(
                {
                    "title": f"{course_code} Examination",
                    "subject": course_code,
                    "deadline": current_datetime,
                    "description": combined_text,
                }
            )

    for line in lines:
        upper_line = line.upper()

        if "PRACTICAL EXAMINATION" in upper_line:
            process_current_block()
            break

        date_match = DATE_PATTERN.search(line)

        if date_match:
            process_current_block()

            day, month, year = map(
                int,
                date_match.groups(),
            )

            try:
                current_datetime = datetime(
                    year,
                    month,
                    day,
                    default_hour,
                    default_minute,
                )
            except ValueError:
                current_datetime = None
                current_lines = []
                continue

            current_lines = [line]

        elif current_datetime is not None:
            current_lines.append(line)

    else:
        process_current_block()

    return sorted(
        events,
        key=lambda event: (
            event["deadline"],
            event["subject"],
        ),
    )
def extract_practical_exam_events(
    text: str,
    default_hour: int,
    default_minute: int,
) -> list[dict[str, Any]]:
    """
    Extract practical examination rows.

    Example OCR text:

    MBA 12-08-2026 to 14-08-2026 MILBA207
    MCA 13-08-2026 to 14-08-2026 MOLCA206 MPLCA207
    """

    events: list[dict[str, Any]] = []
    seen_events: set[tuple[str, str]] = set()

    practical_pattern = re.compile(
        r"\b(MBA|MCA)\b"
        r".{0,20}?"
        r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})"
        r"\s*(?:to|-)\s*"
        r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})"
        r"(.+)",
        re.IGNORECASE,
    )

    for line in text.splitlines():
        cleaned_line = line.strip()

        if not cleaned_line:
            continue

        match = practical_pattern.search(
            cleaned_line
        )

        if not match:
            continue

        (
            program_name,
            start_day,
            start_month,
            start_year,
            _end_day,
            _end_month,
            _end_year,
            codes_text,
        ) = match.groups()

        try:
            practical_datetime = datetime(
                int(start_year),
                int(start_month),
                int(start_day),
                default_hour,
                default_minute,
            )
        except ValueError:
            continue

        course_codes = extract_course_codes(
            codes_text
        )

        for course_code in course_codes:
            event_key = (
                course_code,
                practical_datetime.isoformat(),
            )

            if event_key in seen_events:
                continue

            seen_events.add(event_key)

            events.append(
                {
                    "title": f"{course_code} Practical Examination",
                    "subject": course_code,
                    "deadline": practical_datetime,
                    "description": (
                        f"{program_name.upper()} practical examination: "
                        f"{cleaned_line}"
                    ),
                }
            )

    return events


def extract_exam_events(
    text: str,
    default_hour: int = 14,
    default_minute: int = 0,
) -> list[dict[str, Any]]:
    theory_events = extract_theory_exam_events(
        text=text,
        default_hour=default_hour,
        default_minute=default_minute,
    )

    practical_events = extract_practical_exam_events(
        text=text,
        default_hour=default_hour,
        default_minute=default_minute,
    )

    combined_events = theory_events + practical_events

    unique_events: list[dict[str, Any]] = []
    seen_events: set[tuple[str, str]] = set()

    for event in combined_events:
        event_key = (
            str(event["subject"]).upper(),
            event["deadline"].isoformat(),
        )

        if event_key in seen_events:
            continue

        seen_events.add(event_key)
        unique_events.append(event)

    return sorted(
        unique_events,
        key=lambda event: (
            event["deadline"],
            event["subject"],
        ),
    )
def filter_events_by_program(
    events: list[dict[str, Any]],
    program: str,
) -> list[dict[str, Any]]:
    """Filter examination events by course-code structure."""

    selected_program = program.strip().upper()

    if selected_program == "ALL":
        return events

    filtered_events: list[dict[str, Any]] = []

    for event in events:
        course_code = str(
            event.get("subject", "")
        ).strip().upper()

        is_mca = bool(
            re.fullmatch(
                r"[A-Z]{2,6}CA\d{3}",
                course_code,
            )
        )

        is_mba = bool(
            re.fullmatch(
                r"[A-Z]{2,6}BA\d{3}",
                course_code,
            )
        )

        if selected_program == "MCA" and is_mca:
            filtered_events.append(event)

        elif selected_program == "MBA" and is_mba:
            filtered_events.append(event)

    return filtered_events
def correct_course_code(code: str) -> str:
    """
    Clean and correct common OCR mistakes in course codes.

    Examples:
    MMLCA201
    MGACA352
    MDSCA102
    MFMBA202
    """

    cleaned_code = re.sub(
        r"[^A-Z0-9]",
        "",
        str(code).upper(),
    )

    # Minimum: 4 letters + 3 number-like characters.
    if len(cleaned_code) < 7:
        return ""

    prefix = cleaned_code[:-3]
    number_part = cleaned_code[-3:]

    number_replacements = {
        "O": "0",
        "Q": "0",
        "D": "0",
        "I": "1",
        "L": "1",
        "Z": "2",
        "S": "5",
        "B": "8",
        "G": "6",
    }

    corrected_number = "".join(
        number_replacements.get(character, character)
        for character in number_part
    )

    prefix_replacements = {
        "0": "O",
        "1": "I",
        "2": "Z",
        "5": "S",
        "8": "B",
    }

    corrected_prefix = "".join(
        prefix_replacements.get(character, character)
        for character in prefix
    )

    if not corrected_prefix.isalpha():
        return ""

    if not corrected_number.isdigit():
        return ""

    corrected_code = corrected_prefix + corrected_number

    if not re.fullmatch(
        r"[A-Z]{4,8}\d{3}",
        corrected_code,
    ):
        return ""

    if (
        "BA" not in corrected_code
        and "CA" not in corrected_code
    ):
        return ""

    return corrected_code
def is_valid_course_code(
    course_code: str,
) -> bool:
    """
    Validate course codes after OCR correction.
    """

    normalized_code = course_code.strip().upper()

    return bool(
        re.fullmatch(
            r"[A-Z]{4,8}\d{3}",
            normalized_code,
        )
    )

def extract_exam_events_from_rows(
    timetable_rows: list[str],
    default_hour: int = 14,
    default_minute: int = 0,
) -> list[dict[str, Any]]:
    """
    Convert detected timetable rows into examination events.
    """

    events: list[dict[str, Any]] = []
    seen_events: set[tuple[str, str]] = set()

    date_pattern = re.compile(
        r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b"
    )

    for row in timetable_rows:
        parts = [
            part.strip()
            for part in row.split("|")
            if part.strip()
        ]

        if not parts:
            continue

        # Practical row:
        # MBA | 12-08-2026 to 14-08-2026 | MILBA207
        first_part = re.sub(
                 r"[^A-Z]",
                 "",
          parts[0].upper(),
              )

        if first_part in {"MBA", "MCA"}:
            if len(parts) < 3:
                continue

            date_match = date_pattern.search(parts[1])

            if not date_match:
                continue

            day, month, year = map(
                int,
                date_match.groups(),
            )

            try:
                exam_datetime = datetime(
                    year,
                    month,
                    day,
                    default_hour,
                    default_minute,
                )
            except ValueError:
                continue

            subject_parts: list[str] = []

            for part in parts[2:]:
                possible_subjects = re.split(
                r"[,;/\s]+",
                part,
            )

                subject_parts.extend(
                subject
                for subject in possible_subjects
                 if subject.strip()
            )

            practical = True

        # Theory row:
        # 04-08-2026 | MBABA102 | MMMBA105 | MITBA302
        else:
            date_match = date_pattern.search(parts[0])

            if not date_match:
                continue

            day, month, year = map(
                int,
                date_match.groups(),
            )

            try:
                exam_datetime = datetime(
                    year,
                    month,
                    day,
                    default_hour,
                    default_minute,
                )
            except ValueError:
                continue

            subject_parts = []

            for part in parts[1:]:
               subject_parts.extend(
                  re.split(r"[,;/\s]+", part)
                   )

            practical = False

        for raw_subject in subject_parts:
            course_code = correct_course_code(
                raw_subject
            )
            print(
            "RAW:", raw_subject,
                "->",
              course_code,
              )
            if not course_code:
                continue

            if not is_valid_course_code(course_code):
                continue

            event_key = (
                course_code,
                exam_datetime.isoformat(),
            )

            if event_key in seen_events:
                continue

            seen_events.add(event_key)

            if practical:
                title = (
                    f"{course_code} Practical Examination"
                )
            else:
                title = f"{course_code} Examination"

            events.append(
                {
                    "title": title,
                    "subject": course_code,
                    "deadline": exam_datetime,
                    "description": row,
                }
            )

    return sorted(
        events,
        key=lambda event: (
            event["deadline"],
            event["subject"],
        ),
    )