import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from income_book_automation.models import BankName
from income_book_automation.parsers.errors import (
    BankStatementFormatError,
    BankStatementReadError,
    EmptyBankStatementError,
    InvalidBankRowError,
    InvalidBankRowStructureError,
    MissingBankColumnError,
)
from income_book_automation.parsers.pumb import parse_pumb_file, parse_pumb_row


def _pumb_row() -> dict[str, str]:
    return {
        "ST_NUMB": "TEST-STATEMENT-001",
        "ST_DATE": "2026.07.07",
        "ACC_NUMB": "UA273000010000000000000000001",
        "DOC_DATE": "2026.07.07",
        "CUR_NUMB": "980",
        "DB": "0.00",
        "CR": "100.00",
        "DOC_NO": "TEST-DOC-001",
        "KOR_MFO": "000000",
        "KOR_BANK": "ТЕСТОВИЙ БАНК",
        "KOR_ACC": "UA973000010000000000000000002",
        "KOR_NAME": "ТОВ Тестовий клієнт",
        "KOR_OKPO": "0000000000",
        "DESCRIPT": "Оплата за тестові послуги",
        "UDB": "0.00",
        "UCR": "100.00",
        "RATE": "1.00",
        "": "",
    }


def test_parse_pumb_row_maps_credit_transaction() -> None:
    transaction = parse_pumb_row(
        _pumb_row(),
        Path("synthetic-pumb-tx.csv"),
        2,
    )

    assert transaction.date == date(2026, 7, 7)
    assert transaction.bank is BankName.PUMB
    assert transaction.account_number == "UA273000010000000000000000001"
    assert transaction.currency == "UAH"
    assert transaction.document_number == "TEST-DOC-001"
    assert transaction.debit == Decimal("0.00")
    assert transaction.credit == Decimal("100.00")
    assert transaction.counterparty == "ТОВ Тестовий клієнт"
    assert transaction.counterparty_account == "UA973000010000000000000000002"
    assert transaction.payment_purpose == "Оплата за тестові послуги"
    assert transaction.counterparty_tax_id == "0000000000"
    assert transaction.source.original_filename == "synthetic-pumb-tx.csv"
    assert transaction.source.row_number == 2


def test_parse_pumb_row_converts_empty_tax_id_to_none() -> None:
    row = _pumb_row()
    row["KOR_OKPO"] = ""

    transaction = parse_pumb_row(
        row,
        Path("synthetic-pumb-tx.csv"),
        2,
    )

    assert transaction.counterparty_tax_id is None


@pytest.mark.parametrize(
    ("column_name", "value"),
    [
        ("ACC_NUMB", ""),
        ("CUR_NUMB", "   "),
    ],
)
def test_parse_pumb_row_rejects_missing_technical_value(
    column_name: str,
    value: str,
) -> None:
    row = _pumb_row()
    row[column_name] = value

    with pytest.raises(
        InvalidBankRowError,
        match=rf"column '{column_name}': required value is missing",
    ):
        parse_pumb_row(row, Path("synthetic-pumb.csv"), 7)


def test_parse_pumb_file_reads_cp1251_rows(tmp_path: Path) -> None:
    credit_row = _pumb_row()
    debit_row = _pumb_row()
    debit_row["ST_DATE"] = "2026.07.08"
    debit_row["DOC_DATE"] = "2026.07.08"
    debit_row["DOC_NO"] = "TEST-DOC-002"
    debit_row["DB"] = "25.00"
    debit_row["CR"] = "0.00"

    source_path = tmp_path / "synthetic-pumb-tx.csv"
    with source_path.open("w", encoding="cp1251", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=credit_row.keys(),
            delimiter=";",
        )
        writer.writeheader()
        writer.writerows([credit_row, debit_row])

    transactions = parse_pumb_file(source_path)

    assert len(transactions) == 2
    assert transactions[0].credit == Decimal("100.00")
    assert transactions[0].debit == Decimal("0.00")
    assert transactions[1].credit == Decimal("0.00")
    assert transactions[1].debit == Decimal("25.00")
    assert transactions[1].date == date(2026, 7, 8)


def test_parse_pumb_file_rejects_missing_required_header(
    tmp_path: Path,
) -> None:
    row = _pumb_row()
    del row["CR"]

    source_path = tmp_path / "missing-header-pumb.csv"
    with source_path.open("w", encoding="cp1251", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=row.keys(), delimiter=";")
        writer.writeheader()
        writer.writerow(row)

    with pytest.raises(MissingBankColumnError, match="'CR'"):
        parse_pumb_file(source_path)


@pytest.mark.parametrize(
    ("extra_values", "expected_column_count"),
    [
        (-1, 17),
        (1, 19),
    ],
)
def test_parse_pumb_file_rejects_wrong_row_width(
    tmp_path: Path,
    extra_values: int,
    expected_column_count: int,
) -> None:
    row = _pumb_row()
    values = list(row.values())

    if extra_values < 0:
        values = values[:extra_values]
    else:
        values.extend(["UNEXPECTED"] * extra_values)

    source_path = tmp_path / "damaged-pumb.csv"
    with source_path.open("w", encoding="cp1251", newline="") as file:
        writer = csv.writer(file, delimiter=";")
        writer.writerow(row.keys())
        writer.writerow(values)

    with pytest.raises(
        InvalidBankRowStructureError,
        match=(
            "File 'damaged-pumb.csv', bank 'PUMB', row 2: "
            f"expected 18 columns, got {expected_column_count}"
        ),
    ):
        parse_pumb_file(source_path)


def test_parse_pumb_file_rejects_header_without_transactions(
    tmp_path: Path,
) -> None:
    row = _pumb_row()
    source_path = tmp_path / "header-only-pumb.csv"

    with source_path.open("w", encoding="cp1251", newline="") as file:
        writer = csv.writer(file, delimiter=";")
        writer.writerow(row.keys())

    with pytest.raises(
        EmptyBankStatementError,
        match="statement contains no transaction rows",
    ):
        parse_pumb_file(source_path)


def test_parse_pumb_row_wraps_unknown_currency() -> None:
    row = _pumb_row()
    row["CUR_NUMB"] = "999"

    with pytest.raises(
        InvalidBankRowError,
        match="row 7, column 'CUR_NUMB': unsupported currency code",
    ):
        parse_pumb_row(row, Path("synthetic-pumb.csv"), 7)


def test_parse_pumb_row_wraps_invalid_transaction_values() -> None:
    row = _pumb_row()
    row["DB"] = "0.00"
    row["CR"] = "0.00"

    with pytest.raises(
        InvalidBankRowError,
        match="row 7: invalid transaction values",
    ):
        parse_pumb_row(row, Path("synthetic-pumb.csv"), 7)


def test_parse_pumb_file_rejects_empty_file(tmp_path: Path) -> None:
    source_path = tmp_path / "empty-pumb.csv"
    source_path.write_text("", encoding="cp1251")

    with pytest.raises(BankStatementFormatError, match="CSV header row is missing"):
        parse_pumb_file(source_path)


def test_parse_pumb_file_wraps_missing_file(tmp_path: Path) -> None:
    source_path = tmp_path / "missing-pumb.csv"

    with pytest.raises(BankStatementReadError, match="missing-pumb.csv"):
        parse_pumb_file(source_path)


@pytest.mark.parametrize("column_name", ["ACC_NUMB", "KOR_ACC"])
def test_parse_pumb_row_rejects_invalid_iban(column_name: str) -> None:
    row = _pumb_row()
    row[column_name] = "UA003000010000000000000000001"

    with pytest.raises(
        InvalidBankRowError,
        match=rf"column '{column_name}': invalid Ukrainian IBAN",
    ):
        parse_pumb_row(row, Path("synthetic-pumb.csv"), 7)


def test_parse_pumb_row_accepts_non_iban_counterparty_account() -> None:
    row = _pumb_row()
    row["KOR_ACC"] = "26001234567890"

    transaction = parse_pumb_row(row, Path("synthetic-pumb.csv"), 7)

    assert transaction.counterparty_account == "26001234567890"
