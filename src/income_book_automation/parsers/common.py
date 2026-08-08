import csv
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal, TextIO

from income_book_automation.parsers.errors import (
    BankStatementFormatError,
    BankStatementReadError,
    InvalidBankRowError,
    MissingBankColumnError,
)

DateOrder = Literal["YMD", "DMY"]


def validate_required_headers(
    fieldnames: list[str] | None, required_headers: set[str], path: Path
) -> None:
    if fieldnames is None:
        raise BankStatementFormatError(f"File '{path.name}': CSV header row is missing")

    available_headers = {header for header in fieldnames if header}

    missing_headers = sorted(required_headers - available_headers)

    if missing_headers:
        missing = ", ".join(f"'{header}'" for header in missing_headers)

        raise MissingBankColumnError(
            f"File '{path.name}': required columns are missing: {missing}"
        )


def parse_decimal_value(
    value: str,
    path: Path,
    row_number: int,
    column_name: str,
) -> Decimal:
    try:
        normalized_value = (
            value.strip().replace(" ", "").replace("\u00a0", "").replace(",", ".")
        )

        result = Decimal(normalized_value)

        if not result.is_finite():
            raise InvalidOperation

        return result

    except (AttributeError, InvalidOperation) as error:
        raise InvalidBankRowError(
            f"File '{path.name}', row {row_number}, "
            f"column '{column_name}': invalid monetary value"
        ) from error


def parse_dotted_date(
    value: str,
    path: Path,
    row_number: int,
    column_name: str,
    *,
    order: DateOrder,
) -> date:
    try:
        first, second, third = map(int, value.strip().split("."))

        if order == "YMD":
            year, month, day = first, second, third
        else:
            day, month, year = first, second, third

        return date(year, month, day)

    except (AttributeError, ValueError) as error:
        raise InvalidBankRowError(
            f"File '{path.name}', row {row_number}, "
            f"column '{column_name}': invalid date"
        ) from error


@contextmanager
def open_bank_csv(path: Path, *, encoding: str) -> Iterator[TextIO]:
    try:
        with path.open(
            encoding=encoding,
            newline="",
        ) as file:
            yield file

    except (OSError, UnicodeError, csv.Error) as error:
        raise BankStatementReadError(
            f"Can't read bank statement file '{path.name}'"
        ) from error
