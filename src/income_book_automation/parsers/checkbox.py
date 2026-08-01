"""Parser for Checkbox Z-report workbooks."""

from decimal import Decimal, InvalidOperation
from pathlib import Path

from openpyxl import load_workbook
from pydantic import ValidationError

from income_book_automation.models import DailyCheckboxRevenue

REQUIRED_HEADERS = {
    "opened_at": "Дата відкриття",
    "card_revenue": "Виручка безготівка",
    "card_refund": "Повернення безготівка",
    "cash_revenue": "Виручка готівка",
    "cash_refund": "Повернення готівка",
}


class CheckboxParseError(Exception):
    """Raised when a Checkbox workbook has any error."""


class CheckboxFormatError(CheckboxParseError):
    """Raised when a Checkbox workbook has an unexpected structure."""


class MissingCheckboxColumnError(CheckboxFormatError):
    """Raised when a required Checkbox column is missing."""


class InvalidCheckboxRowError(CheckboxParseError):
    """Raised when a checkbox workbook has a different value."""


def normalize_header(value: object) -> str:
    if value is None:
        return ""

    text = str(value).replace("\u00a0", " ")
    return " ".join(text.split()).casefold()


def resolve_column_headers(
    header_row: tuple[object, ...], path: Path
) -> dict[str, int]:
    available_headers = {
        normalize_header(header): index
        for index, header in enumerate(header_row)
        if header is not None
    }

    indexes: dict[str, int] = {}
    missing_headers: list[str] = []

    for field_name, required_header in REQUIRED_HEADERS.items():
        normalized_header = normalize_header(required_header)

        if normalized_header not in available_headers:
            missing_headers.append(required_header)
            continue
        indexes[field_name] = available_headers[normalized_header]

    if missing_headers:
        missing = ", ".join(f"'{header}'" for header in missing_headers)
        raise MissingCheckboxColumnError(
            f"File '{path.name}', row 1: required columns are missing: "
            f"{missing}. Original value: None"
        )

    return indexes


def parse_checkbox_row(
    row: tuple[object, ...],
    column_indexes: dict[str, int],
    path: Path,
    row_number: int,
) -> DailyCheckboxRevenue:
    opened_at = row[column_indexes["opened_at"]]
    try:
        opened_date = opened_at.date()
    except AttributeError as error:
        raise InvalidCheckboxRowError(
            f"File '{path.name}', row {row_number}, "
            f"column '{REQUIRED_HEADERS['opened_at']}': "
            f"invalid value {opened_at!r}"
        ) from error

    card_revenue_value = row[column_indexes["card_revenue"]]
    card_revenue = parse_decimal_value(
        card_revenue_value,
        path,
        row_number,
        REQUIRED_HEADERS["card_revenue"],
    )

    card_refund_value = row[column_indexes["card_refund"]]
    card_refund = parse_decimal_value(
        card_refund_value,
        path,
        row_number,
        REQUIRED_HEADERS["card_refund"],
    )

    cash_revenue_value = row[column_indexes["cash_revenue"]]
    cash_revenue = parse_decimal_value(
        cash_revenue_value,
        path,
        row_number,
        REQUIRED_HEADERS["cash_revenue"],
    )

    cash_refund_value = row[column_indexes["cash_refund"]]
    cash_refund = parse_decimal_value(
        cash_refund_value,
        path,
        row_number,
        REQUIRED_HEADERS["cash_refund"],
    )

    try:
        return DailyCheckboxRevenue(
            date=opened_date,
            card_revenue=card_revenue,
            card_refund=card_refund,
            cash_revenue=cash_revenue,
            cash_refund=cash_refund,
        )
    except ValidationError as error:
        raise InvalidCheckboxRowError(
            f"File '{path.name}', row {row_number}: invalid monetary values"
        ) from error


def parse_decimal_value(
    value: object, path: Path, row_number: int, column_name: str
) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except InvalidOperation as error:
        raise InvalidCheckboxRowError(
            f"File '{path.name}', row {row_number}, "
            f"column '{column_name}': "
            f"invalid value {value!r}"
        ) from error


def parse_checkbox_file(path: Path) -> list[DailyCheckboxRevenue]:
    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
    except Exception as error:
        raise CheckboxParseError(
            f"Can't read Checkbox file: '{path.name}' the file is corrupted or has an invalid format."
        ) from error

    try:
        worksheet = workbook.active
        rows = worksheet.iter_rows(values_only=True)

        header_row = next(rows, None)

        if header_row is None:
            raise CheckboxFormatError("Checkbox workbook is empty.")

        column_indexes = resolve_column_headers(header_row, path)

        records: list[DailyCheckboxRevenue] = []

        for row_number, row in enumerate(rows, start=2):
            opened_at = row[column_indexes["opened_at"]]

            if opened_at is None:
                continue

            record = parse_checkbox_row(row, column_indexes, path, row_number)
            records.append(record)

        return records

    finally:
        workbook.close()
