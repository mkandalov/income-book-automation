import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from income_book_automation.models import BankName
from income_book_automation.parsers.errors import (
    BankStatementReadError,
    EmptyBankStatementError,
    InvalidBankRowError,
    InvalidBankRowStructureError,
    MissingBankColumnError,
)
from income_book_automation.parsers.privat import (
    parse_privat_file,
    parse_privat_row,
)


def _privat_row() -> dict[str, str]:
    return {
        "ЄДРПОУ": "1111111111",
        "МФО": "000000",
        "Рахунок": "UA273000010000000000000000001",
        "Валюта": "UAH",
        "Номер документу": "TEST-DOC-001",
        "Дата операції": "07.07.2026",
        "МФО банку": "000001",
        "Назва банку": "ТЕСТОВИЙ БАНК",
        "Рахунок кореспондента": "UA973000010000000000000000002",
        "ЄДРПОУ кореспондента": "0000000000",
        "Кореспондент": "ТОВ Тестовий клієнт",
        "Сума": "100.00",
        "Призначення платежу": "Оплата за тестові послуги",
        "": "",
    }


def test_parse_privat_row_maps_positive_amount_to_credit() -> None:
    transaction = parse_privat_row(
        _privat_row(),
        Path("synthetic-privat.csv"),
        2,
    )

    assert transaction.date == date(2026, 7, 7)
    assert transaction.bank is BankName.PRIVAT
    assert transaction.currency == "UAH"
    assert transaction.debit == Decimal("0.00")
    assert transaction.credit == Decimal("100.00")
    assert transaction.counterparty == "ТОВ Тестовий клієнт"
    assert transaction.counterparty_account == "UA973000010000000000000000002"
    assert transaction.counterparty_tax_id == "0000000000"
    assert transaction.source.original_filename == "synthetic-privat.csv"
    assert transaction.source.row_number == 2


def test_parse_privat_row_removes_thousands_separators() -> None:
    row = _privat_row()
    row["Сума"] = "12 345.67"

    transaction = parse_privat_row(
        row,
        Path("synthetic-privat.csv"),
        2,
    )

    assert transaction.credit == Decimal("12345.67")
    assert transaction.debit == Decimal("0.00")


@pytest.mark.parametrize(
    "column_name",
    ["Рахунок", "Валюта"],
)
def test_parse_privat_row_rejects_missing_technical_value(
    column_name: str,
) -> None:
    row = _privat_row()
    row[column_name] = "   "

    with pytest.raises(
        InvalidBankRowError,
        match=rf"column '{column_name}': required value is missing",
    ):
        parse_privat_row(row, Path("synthetic-privat.csv"), 7)


def test_parse_privat_row_rejects_zero_amount() -> None:
    row = _privat_row()
    row["Сума"] = "0.00"

    with pytest.raises(
        InvalidBankRowError,
        match="column 'Сума': transaction amount must be non-zero",
    ):
        parse_privat_row(row, Path("synthetic-privat.csv"), 7)


def test_parse_privat_file_reads_cp1251_and_signed_amounts(
    tmp_path: Path,
) -> None:
    credit_row = _privat_row()
    debit_row = _privat_row()
    debit_row["Дата операції"] = "08.07.2026"
    debit_row["Номер документу"] = "TEST-DOC-002"
    debit_row["Сума"] = "-25.00"

    source_path = tmp_path / "synthetic-privat.csv"
    with source_path.open("w", encoding="cp1251", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=credit_row.keys(),
            delimiter=";",
        )
        writer.writeheader()
        writer.writerows([credit_row, debit_row])

    transactions = parse_privat_file(source_path)

    assert len(transactions) == 2
    assert transactions[0].credit == Decimal("100.00")
    assert transactions[1].debit == Decimal("25.00")
    assert transactions[1].credit == Decimal("0.00")
    assert transactions[1].date == date(2026, 7, 8)


def test_parse_privat_file_rejects_missing_required_header(
    tmp_path: Path,
) -> None:
    row = _privat_row()
    del row["Сума"]

    source_path = tmp_path / "missing-header-privat.csv"
    with source_path.open("w", encoding="cp1251", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=row.keys(), delimiter=";")
        writer.writeheader()
        writer.writerow(row)

    with pytest.raises(MissingBankColumnError, match="Сума"):
        parse_privat_file(source_path)


@pytest.mark.parametrize(
    ("extra_values", "actual_column_count"),
    [
        (-1, 13),
        (1, 15),
    ],
)
def test_parse_privat_file_rejects_wrong_row_width(
    tmp_path: Path,
    extra_values: int,
    actual_column_count: int,
) -> None:
    row = _privat_row()
    values = list(row.values())

    if extra_values < 0:
        values = values[:extra_values]
    else:
        values.extend(["UNEXPECTED"] * extra_values)

    source_path = tmp_path / "damaged-privat.csv"
    with source_path.open("w", encoding="cp1251", newline="") as file:
        writer = csv.writer(file, delimiter=";")
        writer.writerow(row.keys())
        writer.writerow(values)

    with pytest.raises(
        InvalidBankRowStructureError,
        match=(
            "File 'damaged-privat.csv', bank 'PrivatBank', row 2: "
            f"expected 14 columns, got {actual_column_count}"
        ),
    ):
        parse_privat_file(source_path)


def test_parse_privat_file_rejects_header_without_transactions(
    tmp_path: Path,
) -> None:
    row = _privat_row()
    source_path = tmp_path / "header-only-privat.csv"

    with source_path.open("w", encoding="cp1251", newline="") as file:
        writer = csv.writer(file, delimiter=";")
        writer.writerow(row.keys())

    with pytest.raises(
        EmptyBankStatementError,
        match="statement contains no transaction rows",
    ):
        parse_privat_file(source_path)


def test_parse_privat_row_wraps_invalid_date() -> None:
    row = _privat_row()
    row["Дата операції"] = "wrong-date"

    with pytest.raises(
        InvalidBankRowError,
        match="row 7, column 'Дата операції': invalid date",
    ):
        parse_privat_row(row, Path("synthetic-privat.csv"), 7)


def test_parse_privat_file_wraps_missing_file(tmp_path: Path) -> None:
    source_path = tmp_path / "missing-privat.csv"

    with pytest.raises(BankStatementReadError, match="missing-privat.csv"):
        parse_privat_file(source_path)


@pytest.mark.parametrize(
    "column_name",
    ["Рахунок", "Рахунок кореспондента"],
)
def test_parse_privat_row_rejects_invalid_iban(column_name: str) -> None:
    row = _privat_row()
    row[column_name] = "UA003000010000000000000000001"

    with pytest.raises(
        InvalidBankRowError,
        match=rf"column '{column_name}': invalid Ukrainian IBAN",
    ):
        parse_privat_row(row, Path("synthetic-privat.csv"), 7)


def test_parse_privat_row_accepts_non_iban_counterparty_account() -> None:
    row = _privat_row()
    row["Рахунок кореспондента"] = "26001234567890"

    transaction = parse_privat_row(row, Path("synthetic-privat.csv"), 7)

    assert transaction.counterparty_account == "26001234567890"
