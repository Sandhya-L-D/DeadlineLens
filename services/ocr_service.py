"""
OCR services for DeadlineLens.

This module provides:
1. General document text extraction using EasyOCR.
2. Timetable-row extraction using EasyOCR coordinates.
3. Optional word-level extraction using Tesseract.
4. OCR preprocessing and row-grouping helpers.

EasyOCR is loaded lazily and cached so that Streamlit does not
reload the machine-learning model after every application rerun.
"""

from __future__ import annotations

import os
import re
import shutil
from functools import lru_cache
from typing import Any

import cv2
import numpy as np
import pytesseract
from PIL import Image
from pytesseract import Output


# -------------------------------------------------------------------
# Tesseract configuration
# -------------------------------------------------------------------

WINDOWS_TESSERACT_PATH = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)


def configure_tesseract() -> None:
    """
    Configure the Tesseract executable safely.

    On Windows, DeadlineLens uses the standard Tesseract installation
    path when it exists.

    On Streamlit Community Cloud or Linux, the executable is located
    automatically through the system PATH.
    """

    if os.path.exists(WINDOWS_TESSERACT_PATH):
        pytesseract.pytesseract.tesseract_cmd = (
            WINDOWS_TESSERACT_PATH
        )
        return

    detected_path = shutil.which("tesseract")

    if detected_path:
        pytesseract.pytesseract.tesseract_cmd = (
            detected_path
        )


configure_tesseract()


# -------------------------------------------------------------------
# EasyOCR model loading
# -------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_easyocr_reader() -> Any:
    """
    Load and cache the EasyOCR reader.

    Importing EasyOCR inside this function prevents the model from
    loading when the Streamlit application initially starts.

    The model is downloaded and initialized only when OCR is actually
    requested by the user.
    """

    try:
        import easyocr
    except ImportError as error:
        raise RuntimeError(
            "EasyOCR is not installed. Add 'easyocr' to "
            "requirements.txt and reinstall the dependencies."
        ) from error

    return easyocr.Reader(
        ["en"],
        gpu=False,
        verbose=False,
        download_enabled=True,
    )


# -------------------------------------------------------------------
# General text utilities
# -------------------------------------------------------------------

def clean_ocr_text(text: str) -> str:
    """
    Remove unnecessary spaces while preserving meaningful lines.
    """

    if not text:
        return ""

    cleaned_lines: list[str] = []

    for line in str(text).splitlines():
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
    Prepare an uploaded image for Tesseract OCR.

    Processing steps:
    - Convert to RGB.
    - Convert to grayscale.
    - Enlarge small characters.
    - Apply light denoising.
    - Sharpen the image.
    """

    if image is None:
        raise ValueError("No image was supplied for OCR.")

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


def _prepare_easyocr_image(
    image: Image.Image,
    scale: float = 2.0,
) -> np.ndarray:
    """
    Convert and enlarge an image for EasyOCR.
    """

    if image is None:
        raise ValueError("No image was supplied for OCR.")

    rgb_image = image.convert("RGB")
    image_array = np.array(rgb_image)

    if scale <= 1:
        return image_array

    return cv2.resize(
        image_array,
        None,
        fx=scale,
        fy=scale,
        interpolation=cv2.INTER_CUBIC,
    )


# -------------------------------------------------------------------
# EasyOCR text extraction
# -------------------------------------------------------------------

def extract_text(image: Image.Image) -> str:
    """
    Extract readable document text using EasyOCR.

    OCR words are grouped into approximate text lines using their
    bounding-box coordinates.
    """

    try:
        prepared_image = _prepare_easyocr_image(
            image,
            scale=2.0,
        )

        reader = get_easyocr_reader()

        results = reader.readtext(
            prepared_image,
            detail=1,
            paragraph=False,
            decoder="greedy",
            text_threshold=0.6,
            low_text=0.3,
            link_threshold=0.4,
            mag_ratio=1.5,
        )

    except Exception as error:
        raise RuntimeError(
            f"EasyOCR could not process the uploaded image: {error}"
        ) from error

    detected_items: list[dict[str, Any]] = []

    for result in results:
        if not isinstance(result, (list, tuple)):
            continue

        if len(result) != 3:
            continue

        box, text, confidence = result

        cleaned_text = str(text).strip()

        if not cleaned_text:
            continue

        try:
            confidence_value = float(confidence)
        except (TypeError, ValueError):
            confidence_value = 0.0

        if confidence_value < 0.20:
            continue

        try:
            x_values = [
                float(point[0])
                for point in box
            ]

            y_values = [
                float(point[1])
                for point in box
            ]
        except (TypeError, ValueError, IndexError):
            continue

        if not x_values or not y_values:
            continue

        detected_items.append(
            {
                "text": cleaned_text,
                "confidence": confidence_value,
                "x": min(x_values),
                "y": min(y_values),
                "height": max(y_values) - min(y_values),
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

        previous_average_height = sum(
            max(
                1.0,
                float(previous_item["height"]),
            )
            for previous_item in previous_line
        ) / len(previous_line)

        tolerance = max(
            12.0,
            item_height * 0.65,
            previous_average_height * 0.65,
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


# -------------------------------------------------------------------
# Timetable row extraction
# -------------------------------------------------------------------

def extract_timetable_rows(
    image: Image.Image,
) -> list[str]:
    """
    Extract timetable rows containing dates.

    EasyOCR results are grouped by their vertical positions.
    Words in each row are ordered from left to right.
    """

    try:
        prepared_image = _prepare_easyocr_image(
            image,
            scale=2.0,
        )

        reader = get_easyocr_reader()

        results = reader.readtext(
            prepared_image,
            detail=1,
            paragraph=False,
            decoder="greedy",
            text_threshold=0.5,
            low_text=0.25,
            link_threshold=0.4,
        )

    except Exception as error:
        raise RuntimeError(
            f"Timetable OCR could not process the image: {error}"
        ) from error

    words: list[dict[str, Any]] = []

    for result in results:
        if not isinstance(result, (list, tuple)):
            continue

        if len(result) != 3:
            continue

        box, text, confidence = result

        cleaned_text = str(text).strip()

        if not cleaned_text:
            continue

        try:
            confidence_value = float(confidence)
        except (TypeError, ValueError):
            confidence_value = 0.0

        if confidence_value < 0.18:
            continue

        try:
            x_values = [
                float(point[0])
                for point in box
            ]

            y_values = [
                float(point[1])
                for point in box
            ]
        except (TypeError, ValueError, IndexError):
            continue

        if not x_values or not y_values:
            continue

        words.append(
            {
                "text": cleaned_text,
                "x": min(x_values),
                "y": (
                    min(y_values)
                    + max(y_values)
                ) / 2,
                "height": max(y_values) - min(y_values),
            }
        )

    if not words:
        return []

    words.sort(
        key=lambda word: (
            float(word["y"]),
            float(word["x"]),
        )
    )

    grouped_rows: list[list[dict[str, Any]]] = []

    for word in words:
        matching_row: list[dict[str, Any]] | None = None

        word_y = float(word["y"])
        word_height = max(
            1.0,
            float(word["height"]),
        )

        for row in grouped_rows:
            row_average_y = sum(
                float(item["y"])
                for item in row
            ) / len(row)

            row_average_height = sum(
                max(
                    1.0,
                    float(item["height"]),
                )
                for item in row
            ) / len(row)

            tolerance = max(
                14.0,
                word_height * 0.65,
                row_average_height * 0.65,
            )

            if abs(word_y - row_average_y) <= tolerance:
                matching_row = row
                break

        if matching_row is None:
            grouped_rows.append([word])
        else:
            matching_row.append(word)

    timetable_rows: list[str] = []

    date_pattern = re.compile(
        r"\b\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\b"
    )

    date_range_pattern = re.compile(
        r"\b"
        r"\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}"
        r"\s*(?:to|-)\s*"
        r"\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}"
        r"\b",
        flags=re.IGNORECASE,
    )

    for row in grouped_rows:
        row.sort(
            key=lambda word: float(word["x"])
        )

        row_text = " | ".join(
            str(word["text"]).strip()
            for word in row
            if str(word["text"]).strip()
        )

        row_text = clean_ocr_text(row_text)

        if not row_text:
            continue

        if (
            date_pattern.search(row_text)
            or date_range_pattern.search(row_text)
        ):
            timetable_rows.append(row_text)

    # Remove repeated rows while preserving their original order.
    unique_rows: list[str] = []
    seen_rows: set[str] = set()

    for row in timetable_rows:
        normalized_row = row.upper().strip()

        if normalized_row in seen_rows:
            continue

        seen_rows.add(normalized_row)
        unique_rows.append(row)

    return unique_rows


# -------------------------------------------------------------------
# Tesseract word extraction
# -------------------------------------------------------------------

def is_tesseract_available() -> bool:
    """
    Return True when the Tesseract executable is available.
    """

    configured_path = (
        pytesseract.pytesseract.tesseract_cmd
    )

    if configured_path and os.path.exists(configured_path):
        return True

    return shutil.which("tesseract") is not None


def extract_ocr_words(
    image: Image.Image,
) -> list[dict[str, Any]]:
    """
    Extract OCR words with coordinates using Tesseract.

    This helper is optional. If Tesseract is unavailable, an empty
    list is returned instead of crashing the Streamlit application.
    """

    if not is_tesseract_available():
        return []

    prepared_image = prepare_image(image)

    try:
        ocr_data = pytesseract.image_to_data(
            prepared_image,
            config="--oem 3 --psm 6",
            output_type=Output.DICT,
        )
    except Exception:
        return []

    words: list[dict[str, Any]] = []

    total_items = len(
        ocr_data.get("text", [])
    )

    for index in range(total_items):
        text = str(
            ocr_data["text"][index]
        ).strip()

        if not text:
            continue

        try:
            confidence = float(
                ocr_data["conf"][index]
            )
        except (TypeError, ValueError):
            confidence = -1.0

        if confidence < 20:
            continue

        try:
            word = {
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
        except (
            TypeError,
            ValueError,
            KeyError,
            IndexError,
        ):
            continue

        words.append(word)

    return words


# -------------------------------------------------------------------
# Row-grouping helpers
# -------------------------------------------------------------------

def group_words_into_rows(
    words: list[dict[str, Any]],
    row_tolerance: int = 25,
) -> list[list[dict[str, Any]]]:
    """
    Group Tesseract words that appear on approximately the same row.

    Words inside every row are sorted from left to right.
    """

    if not words:
        return []

    sorted_words = sorted(
        words,
        key=lambda word: (
            int(word.get("top", 0)),
            int(word.get("left", 0)),
        ),
    )

    rows: list[list[dict[str, Any]]] = []

    for word in sorted_words:
        word_center_y = (
            int(word.get("top", 0))
            + int(word.get("height", 0)) / 2
        )

        matching_row: list[dict[str, Any]] | None = None

        for row in rows:
            row_centers = [
                (
                    int(item.get("top", 0))
                    + int(item.get("height", 0)) / 2
                )
                for item in row
            ]

            average_row_y = (
                sum(row_centers)
                / len(row_centers)
            )

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
            key=lambda word: int(
                word.get("left", 0)
            )
        )

    rows.sort(
        key=lambda row: min(
            int(word.get("top", 0))
            for word in row
        )
    )

    return rows


def _merge_close_positions(
    positions: list[int],
    distance: int = 12,
) -> list[int]:
    """
    Merge nearby detected table-line positions.
    """

    if not positions:
        return []

    sorted_positions = sorted(
        int(position)
        for position in positions
    )

    merged_positions = [
        sorted_positions[0]
    ]

    for position in sorted_positions[1:]:
        previous_position = merged_positions[-1]

        if position - previous_position <= distance:
            merged_positions[-1] = (
                previous_position + position
            ) // 2
        else:
            merged_positions.append(position)

    return merged_positions