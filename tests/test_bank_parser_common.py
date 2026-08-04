from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from income_book_automation.parsers.common import (
    open_bank_csv,
    parse_decimal_value,
    parse_dotted_date,
    validate_required_headers,
)
from income_book_automation.parsers.errors import (
    BankStatementFormatError,
    BankStatementReadError,
    InvalidBankRowError,
    MissingBankColumnError,
)


def test_validate_required_headers_accepts_complete_header() -> None:
    validate_required_headers(
        ["DATE", "AMOUNT", "DESCRIPTION"],
        {"DATE", "AMOUNT"},
        Path("synthetic-bank.csv"),
    )


def test_validate_required_headers_rejects_missing_columns() -> None:
    with pytest.raises(
        MissingBankColumnError,
        match=(
            "File 'synthetic-bank.csv': required columns are missing: 'AMOUNT', 'DATE'"
        ),
    ):
        validate_required_headers(
            ["DESCRIPTION"],
            {"DATE", "AMOUNT"},
            Path("synthetic-bank.csv"),
        )


def test_validate_required_headers_rejects_missing_header_row() -> None:
    with pytest.raises(
        BankStatementFormatError,
        match="File 'empty.csv': CSV header row is missing",
    ):
        validate_required_headers(
            None,
            {"DATE", "AMOUNT"},
            Path("empty.csv"),
        )


def test_parse_decimal_value_normalizes_separators() -> None:
    value = parse_decimal_value(
        "12 345,67",
        Path("synthetic-bank.csv"),
        4,
        "AMOUNT",
    )

    assert value == Decimal("12345.67")


def test_parse_decimal_value_wraps_invalid_value() -> None:
    with pytest.raises(
        InvalidBankRowError,
        match=(
            "File 'synthetic-bank.csv', row 4, column 'AMOUNT': invalid monetary value"
        ),
    ):
        parse_decimal_value(
            "not-a-number",
            Path("synthetic-bank.csv"),
            4,
            "AMOUNT",
        )


@pytest.mark.parametrize(
    ("value", "order", "expected"),
    [
        ("2026.07.08", "YMD", date(2026, 7, 8)),
        ("08.07.2026", "DMY", date(2026, 7, 8)),
    ],
)
def test_parse_dotted_date_supports_bank_date_orders(
    value: str,
    order: str,
    expected: date,
) -> None:
    result = parse_dotted_date(
        value,
        Path("synthetic-bank.csv"),
        4,
        "DATE",
        order=order,
    )

    assert result == expected


def test_parse_dotted_date_wraps_invalid_value() -> None:
    with pytest.raises(
        InvalidBankRowError,
        match=("File 'synthetic-bank.csv', row 4, column 'DATE': invalid date"),
    ):
        parse_dotted_date(
            "wrong-date",
            Path("synthetic-bank.csv"),
            4,
            "DATE",
            order="DMY",
        )


def test_open_bank_csv_wraps_missing_file(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.csv"

    with (
        pytest.raises(
            BankStatementReadError,
            match="Can't read bank statement file 'missing.csv'",
        ),
        open_bank_csv(missing_path, encoding="utf-8"),
    ):
        pass


def test_open_bank_csv_wraps_invalid_encoding(tmp_path: Path) -> None:
    source_path = tmp_path / "invalid-encoding.csv"
    source_path.write_bytes(b"\xff\xfe\xff")

    with (
        pytest.raises(
            BankStatementReadError,
            match="Can't read bank statement file 'invalid-encoding.csv'",
        ),
        open_bank_csv(source_path, encoding="utf-8") as file,
    ):
        file.read()
