from functools import lru_cache
from typing import Any

import cv2
import easyocr
import numpy as np
from PIL import Image

@lru_cache(maxsize=1)
def get_easyocr_reader() -> easyocr.Reader:
    """
    Load the EasyOCR model only once.

    gpu=False is safer for a normal Windows CPU setup.
    """

    return easyocr.Reader(
        ["en"],
        gpu=False,
    )

import re
from typing import Any

import cv2
import numpy as np
import pytesseract
from PIL import Image
from pytesseract import Output


# Tesseract installation path on Windows.
pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)


def clean_ocr_text(text: str) -> str:
    """Remove unnecessary spaces while preserving lines."""

    cleaned_lines = []

    for line in text.splitlines():
        cleaned_line = re.sub(
            r"[ \t]+",
            " ",
            line,
        ).strip()

        if cleaned_line:
            cleaned_lines.append(cleaned_line)

    return "\n".join(cleaned_lines)


def prepare_image(image: Image.Image) -> np.ndarray:
    """
    Prepare an uploaded image for OCR.

    The image is converted to grayscale, enlarged and sharpened.
    """

    rgb_image = image.convert("RGB")
    image_array = np.array(rgb_image)

    gray_image = cv2.cvtColor(
        image_array,
        cv2.COLOR_RGB2GRAY,
    )

    enlarged_image = cv2.resize(
        gray_image,
        None,
        fx=3.0,
        fy=3.0,
        interpolation=cv2.INTER_CUBIC,
    )

    blurred_image = cv2.GaussianBlur(
        enlarged_image,
        (3, 3),
        0,
    )

    sharpened_image = cv2.addWeighted(
        enlarged_image,
        1.5,
        blurred_image,
        -0.5,
        0,
    )

    return sharpened_image


def extract_text(image: Image.Image) -> str:
    """
    Extract document text using EasyOCR.

    Results are grouped into approximate text lines using
    their bounding-box coordinates.
    """

    rgb_image = image.convert("RGB")
    image_array = np.array(rgb_image)

    # Enlarge small timetable characters.
    enlarged_image = cv2.resize(
        image_array,
        None,
        fx=2.0,
        fy=2.0,
        interpolation=cv2.INTER_CUBIC,
    )

    reader = get_easyocr_reader()

    results = reader.readtext(
        enlarged_image,
        detail=1,
        paragraph=False,
        decoder="greedy",
        text_threshold=0.6,
        low_text=0.3,
        link_threshold=0.4,
        mag_ratio=1.5,
    )

    detected_items: list[dict[str, Any]] = []

    for result in results:
        if len(result) != 3:
            continue

        box, text, confidence = result

        cleaned_text = str(text).strip()

        if not cleaned_text:
            continue

        if float(confidence) < 0.25:
            continue

        x_values = [
            float(point[0])
            for point in box
        ]

        y_values = [
            float(point[1])
            for point in box
        ]

        detected_items.append(
            {
                "text": cleaned_text,
                "confidence": float(confidence),
                "x": min(x_values),
                "y": min(y_values),
                "height": (
                    max(y_values) - min(y_values)
                ),
            }
        )

    if not detected_items:
        return ""

    detected_items.sort(
        key=lambda item: (
            float(item["y"]),
            float(item["x"]),
        )
    )

    grouped_lines: list[list[dict[str, Any]]] = []

    for item in detected_items:
        item_y = float(item["y"])
        item_height = max(
            1.0,
            float(item["height"]),
        )

        if not grouped_lines:
            grouped_lines.append([item])
            continue

        previous_line = grouped_lines[-1]

        previous_average_y = sum(
            float(previous_item["y"])
            for previous_item in previous_line
        ) / len(previous_line)

        tolerance = max(
            12.0,
            item_height * 0.65,
        )

        if abs(item_y - previous_average_y) <= tolerance:
            previous_line.append(item)
        else:
            grouped_lines.append([item])

    output_lines: list[str] = []

    for line_items in grouped_lines:
        line_items.sort(
            key=lambda item: float(item["x"])
        )

        line_text = " ".join(
            str(item["text"])
            for item in line_items
        )

        line_text = clean_ocr_text(line_text)

        if line_text:
            output_lines.append(line_text)

    return "\n".join(output_lines)
def extract_timetable_rows(
    image: Image.Image,
) -> list[str]:
    """
    Read timetable rows using EasyOCR coordinates.
    """

    rgb_image = image.convert("RGB")
    image_array = np.array(rgb_image)

    enlarged_image = cv2.resize(
        image_array,
        None,
        fx=2.0,
        fy=2.0,
        interpolation=cv2.INTER_CUBIC,
    )

    reader = get_easyocr_reader()

    results = reader.readtext(
        enlarged_image,
        detail=1,
        paragraph=False,
    )

    words = []

    for box, text, confidence in results:
        if confidence < 0.20:
            continue

        cleaned_text = str(text).strip()

        if not cleaned_text:
            continue

        x_values = [point[0] for point in box]
        y_values = [point[1] for point in box]

        words.append(
            {
                "text": cleaned_text,
                "x": min(x_values),
                "y": (
                    min(y_values)
                    + max(y_values)
                ) / 2,
                "height": (
                    max(y_values)
                    - min(y_values)
                ),
            }
        )

    words.sort(
        key=lambda word: (
            word["y"],
            word["x"],
        )
    )

    grouped_rows = []

    for word in words:
        added = False

        for row in grouped_rows:
            row_y = sum(
                item["y"]
                for item in row
            ) / len(row)

            if abs(word["y"] - row_y) < 18:
                row.append(word)
                added = True
                break

        if not added:
            grouped_rows.append([word])

    timetable_rows = []

    for row in grouped_rows:
        row.sort(
            key=lambda word: word["x"]
        )

        row_text = " | ".join(
            word["text"]
            for word in row
        )

        if re.search(
            r"\d{1,2}[-/.]\d{1,2}[-/.]\d{4}",
            row_text,
        ):
            timetable_rows.append(row_text)

    return timetable_rows

def _merge_close_positions(
    positions: list[int],
    distance: int = 12,
) -> list[int]:
    """Merge nearby detected table-line positions."""

    if not positions:
        return []

    positions = sorted(positions)
    merged = [positions[0]]

    for position in positions[1:]:
        if position - merged[-1] <= distance:
            merged[-1] = (
                merged[-1] + position
            ) // 2
        else:
            merged.append(position)

    return merged

def extract_ocr_words(
    image: Image.Image,
) -> list[dict[str, Any]]:
    """
    Extract OCR words together with their screen coordinates.

    Each result contains:
    - text
    - left position
    - top position
    - width
    - height
    - confidence
    - line information
    """

    prepared_image = prepare_image(image)

    ocr_data = pytesseract.image_to_data(
        prepared_image,
        config="--oem 3 --psm 6",
        output_type=Output.DICT,
    )

    words: list[dict[str, Any]] = []

    total_items = len(ocr_data["text"])

    for index in range(total_items):
        text = str(
            ocr_data["text"][index]
        ).strip()

        try:
            confidence = float(
                ocr_data["conf"][index]
            )
        except (TypeError, ValueError):
            confidence = -1.0

        if not text:
            continue

        if confidence < 20:
            continue

        words.append(
            {
                "text": text,
                "left": int(
                    ocr_data["left"][index]
                ),
                "top": int(
                    ocr_data["top"][index]
                ),
                "width": int(
                    ocr_data["width"][index]
                ),
                "height": int(
                    ocr_data["height"][index]
                ),
                "confidence": confidence,
                "block_number": int(
                    ocr_data["block_num"][index]
                ),
                "paragraph_number": int(
                    ocr_data["par_num"][index]
                ),
                "line_number": int(
                    ocr_data["line_num"][index]
                ),
            }
        )

    return words


def group_words_into_rows(
    words: list[dict[str, Any]],
    row_tolerance: int = 25,
) -> list[list[dict[str, Any]]]:
    """
    Group OCR words that appear on approximately the same row.

    Words inside each row are sorted from left to right.
    """

    if not words:
        return []

    sorted_words = sorted(
        words,
        key=lambda word: (
            word["top"],
            word["left"],
        ),
    )

    rows: list[list[dict[str, Any]]] = []

    for word in sorted_words:
        word_center_y = (
            word["top"]
            + word["height"] // 2
        )

        matching_row = None

        for row in rows:
            row_centers = [
                item["top"]
                + item["height"] // 2
                for item in row
            ]

            average_row_y = sum(
                row_centers
            ) / len(row_centers)

            if (
                abs(word_center_y - average_row_y)
                <= row_tolerance
            ):
                matching_row = row
                break

        if matching_row is None:
            rows.append([word])
        else:
            matching_row.append(word)

    for row in rows:
        row.sort(
            key=lambda word: word["left"]
        )

    rows.sort(
        key=lambda row: min(
            word["top"]
            for word in row
        )
    )

    return rows
