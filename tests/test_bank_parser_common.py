from collections.abc import Callable
from datetime import date
from decimal import Decimal
from io import StringIO
from pathlib import Path

import pytest

from income_book_automation.parsers.common import (
    open_bank_csv,
    parse_decimal_value,
    parse_dotted_date,
    read_strict_csv_rows,
    require_non_blank_value,
    validate_required_headers,
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


def _read_rows(
    contents: str,
    *,
    delimiter: str = ";",
    header_row_number: int = 1,
    normalize_header: Callable[[str], str] | None = None,
) -> list[tuple[int, dict[str, str]]]:
    return list(
        read_strict_csv_rows(
            StringIO(contents),
            path=Path("synthetic-bank.csv"),
            bank_name="Synthetic Bank",
            delimiter=delimiter,
            required_headers={"DATE", "AMOUNT"},
            header_row_number=header_row_number,
            normalize_header=normalize_header,
        )
    )


def test_read_strict_csv_rows_maps_values_and_row_number() -> None:
    rows = _read_rows("DATE;AMOUNT;DESCRIPTION\n2026.07.01;100.00;Synthetic payment\n")

    assert rows == [
        (
            2,
            {
                "DATE": "2026.07.01",
                "AMOUNT": "100.00",
                "DESCRIPTION": "Synthetic payment",
            },
        )
    ]


def test_read_strict_csv_rows_skips_fully_empty_rows() -> None:
    rows = _read_rows(
        "DATE;AMOUNT;DESCRIPTION\n;;\n2026.07.01;100.00;Synthetic payment\n"
    )

    assert [row_number for row_number, _ in rows] == [3]


@pytest.mark.parametrize(
    ("row", "actual_columns"),
    [
        ("2026.07.01;100.00", 2),
        ("2026.07.01;100.00;Payment;unexpected", 4),
    ],
)
def test_read_strict_csv_rows_rejects_wrong_column_count(
    row: str,
    actual_columns: int,
) -> None:
    with pytest.raises(
        InvalidBankRowStructureError,
        match=(
            "File 'synthetic-bank.csv', bank 'Synthetic Bank', row 2: "
            f"expected 3 columns, got {actual_columns}"
        ),
    ):
        _read_rows(f"DATE;AMOUNT;DESCRIPTION\n{row}\n")


def test_read_strict_csv_rows_rejects_duplicate_headers() -> None:
    with pytest.raises(
        DuplicateBankColumnError,
        match=(
            "File 'synthetic-bank.csv', bank 'Synthetic Bank', row 1: "
            "duplicate CSV columns: 'AMOUNT'"
        ),
    ):
        _read_rows("DATE;AMOUNT;AMOUNT\n2026.07.01;100.00;100.00\n")


def test_read_strict_csv_rows_checks_duplicates_after_normalization() -> None:
    with pytest.raises(DuplicateBankColumnError, match="'AMOUNT'"):
        _read_rows(
            " DATE ;AMOUNT; AMOUNT \n2026.07.01;100.00;100.00\n",
            normalize_header=lambda value: value.strip(),
        )


def test_read_strict_csv_rows_rejects_empty_file() -> None:
    with pytest.raises(
        BankStatementFormatError,
        match=(
            "File 'synthetic-bank.csv', bank 'Synthetic Bank': "
            "CSV header row is missing"
        ),
    ):
        _read_rows("")


def test_read_strict_csv_rows_rejects_file_without_transactions() -> None:
    with pytest.raises(
        EmptyBankStatementError,
        match=(
            "File 'synthetic-bank.csv', bank 'Synthetic Bank': "
            "statement contains no transaction rows"
        ),
    ):
        _read_rows("DATE;AMOUNT;DESCRIPTION\n;;\n")


def test_read_strict_csv_rows_supports_custom_header_row_number() -> None:
    rows = _read_rows(
        "DATE,AMOUNT,DESCRIPTION\n2026.07.01,100.00,Synthetic payment\n",
        delimiter=",",
        header_row_number=2,
    )

    assert rows[0][0] == 3


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


def test_require_non_blank_value_strips_whitespace() -> None:
    result = require_non_blank_value(
        "  UAH  ",
        Path("synthetic-bank.csv"),
        4,
        "CURRENCY",
    )

    assert result == "UAH"


@pytest.mark.parametrize("value", ["", "   ", "\u00a0"])
def test_require_non_blank_value_rejects_missing_value(value: str) -> None:
    with pytest.raises(
        InvalidBankRowError,
        match=(
            "File 'synthetic-bank.csv', row 4, column 'ACCOUNT': "
            "required value is missing"
        ),
    ):
        require_non_blank_value(
            value,
            Path("synthetic-bank.csv"),
            4,
            "ACCOUNT",
        )


def test_parse_decimal_value_identifies_missing_value() -> None:
    with pytest.raises(
        InvalidBankRowError,
        match=(
            "File 'synthetic-bank.csv', row 4, column 'AMOUNT': "
            "required value is missing"
        ),
    ):
        parse_decimal_value(
            "  ",
            Path("synthetic-bank.csv"),
            4,
            "AMOUNT",
        )


def test_parse_dotted_date_identifies_missing_value() -> None:
    with pytest.raises(
        InvalidBankRowError,
        match=(
            "File 'synthetic-bank.csv', row 4, column 'DATE': required value is missing"
        ),
    ):
        parse_dotted_date(
            "  ",
            Path("synthetic-bank.csv"),
            4,
            "DATE",
            order="DMY",
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
