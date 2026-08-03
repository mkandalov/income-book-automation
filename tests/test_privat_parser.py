import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

from income_book_automation.models import BankName
from income_book_automation.parsers.privat import (
    parse_privat_file,
    parse_privat_row,
)


def _privat_row() -> dict[str, str]:
    return {
        "ЄДРПОУ": "1111111111",
        "МФО": "000000",
        "Рахунок": "UA000000000000000000000000001",
        "Валюта": "UAH",
        "Номер документу": "TEST-DOC-001",
        "Дата операції": "07.07.2026",
        "МФО банку": "000001",
        "Назва банку": "ТЕСТОВИЙ БАНК",
        "Рахунок кореспондента": "UA000000000000000000000000002",
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
    assert transaction.counterparty_account == "UA000000000000000000000000002"
    assert transaction.counterparty_tax_id == "0000000000"


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
