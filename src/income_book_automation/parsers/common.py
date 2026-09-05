import csv
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal, TextIO

from income_book_automation.iban import (
    InvalidUkrainianIbanError,
    normalize_account_identifier,
    normalize_ukrainian_iban,
)
from income_book_automation.parsers.errors import (
    BankStatementFormatError,
    BankStatementReadError,
    DuplicateBankColumnError,
    EmptyBankStatementError,
    InvalidBankRowError,
    InvalidBankRowStructureError,
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


def read_strict_csv_rows(
    file: TextIO,
    *,
    path: Path,
    bank_name: str,
    delimiter: str,
    required_headers: set[str],
    header_row_number: int = 1,
    rows_before_header: int = 0,
    normalize_header: Callable[[str], str] | None = None,
) -> Iterator[tuple[int, dict[str, str]]]:
    reader = csv.reader(file, delimiter=delimiter)

    for _ in range(rows_before_header):
        if next(reader, None) is None:
            raise BankStatementFormatError(
                f"File '{path.name}', bank '{bank_name}': CSV header row is missing"
            )

    raw_headers = next(reader, None)

    location = f"File '{path.name}', bank '{bank_name}'"

    if raw_headers is None:
        raise BankStatementFormatError(f"{location}: CSV header row is missing")

    if normalize_header is None:
        headers = raw_headers
    else:
        headers = [normalize_header(header) for header in raw_headers]

    header_counts = Counter(headers)

    duplicate_headers = sorted(
        header for header, count in header_counts.items() if count > 1
    )

    if duplicate_headers:
        formatted_duplicates = ", ".join(
            f"'{header or '<blank>'}'" for header in duplicate_headers
        )

        raise DuplicateBankColumnError(
            f"{location}, row {header_row_number}: "
            f"duplicate CSV columns: {formatted_duplicates}"
        )

    validate_required_headers(
        headers,
        required_headers,
        path,
    )

    expected_column_count = len(headers)
    has_transaction_rows = False

    for row_number, values in enumerate(
        reader,
        start=header_row_number + 1,
    ):
        if all(not value.strip() for value in values):
            continue

        has_transaction_rows = True
        actual_column_count = len(values)

        if actual_column_count != expected_column_count:
            raise InvalidBankRowStructureError(
                f"{location}, row {row_number}: "
                f"expected {expected_column_count} columns, "
                f"got {actual_column_count}"
            )

        yield (
            row_number,
            dict(zip(headers, values, strict=True)),
        )

    if not has_transaction_rows:
        raise EmptyBankStatementError(
            f"{location}: statement contains no transaction rows"
        )


def require_non_blank_value(
    value: str,
    path: Path,
    row_number: int,
    column_name: str,
) -> str:
    try:
        normalized_value = value.strip()
    except AttributeError as error:
        raise InvalidBankRowError(
            f"File '{path.name}', row {row_number}, "
            f"column '{column_name}': required value is missing"
        ) from error

    if not normalized_value:
        raise InvalidBankRowError(
            f"File '{path.name}', row {row_number}, "
            f"column '{column_name}': required value is missing"
        )

    return normalized_value


def parse_ukrainian_iban(
    value: str,
    path: Path,
    row_number: int,
    column_name: str,
    *,
    required: bool,
) -> str:
    normalized_value = "".join(value.split()).upper()

    if not normalized_value and not required:
        return ""

    normalized_value = require_non_blank_value(
        normalized_value,
        path,
        row_number,
        column_name,
    )

    try:
        return normalize_ukrainian_iban(normalized_value)
    except InvalidUkrainianIbanError as error:
        raise InvalidBankRowError(
            f"File '{path.name}', row {row_number}, "
            f"column '{column_name}': invalid Ukrainian IBAN"
        ) from error


def parse_account_identifier(
    value: str,
    path: Path,
    row_number: int,
    column_name: str,
    *,
    required: bool,
) -> str:
    normalized_value = "".join(value.split()).upper()

    if not normalized_value and not required:
        return ""

    normalized_value = require_non_blank_value(
        normalized_value,
        path,
        row_number,
        column_name,
    )

    try:
        return normalize_account_identifier(normalized_value)
    except InvalidUkrainianIbanError as error:
        raise InvalidBankRowError(
            f"File '{path.name}', row {row_number}, "
            f"column '{column_name}': invalid Ukrainian IBAN"
        ) from error


def parse_decimal_value(
    value: str,
    path: Path,
    row_number: int,
    column_name: str,
) -> Decimal:
    normalized_value = require_non_blank_value(
        value,
        path,
        row_number,
        column_name,
    )

    try:
        normalized_value = (
            normalized_value.replace(" ", "").replace("\u00a0", "").replace(",", ".")
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
    normalized_value = require_non_blank_value(
        value,
        path,
        row_number,
        column_name,
    )

    try:
        first, second, third = map(int, normalized_value.split("."))

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
