from decimal import Decimal
from pathlib import Path

import pytest

from income_book_automation.models import BankName
from income_book_automation.parsers.errors import (
    InvalidBankRowError,
    MissingBankColumnError,
)
from income_book_automation.parsers.sense import parse_sense_file

SENSE_HEADERS = [
    "Наш рахунок",
    "Наш IBAN",
    "Операція",
    "Рахунок",
    "IBAN",
    "МФО банку контрагента",
    "Найменування контрагента",
    "Код контрагента",
    "Призначення платежу",
    "Дата проведення",
    "Номер документа",
    "Сума",
    "Валюта",
    "Час проведення",
    "Дата документа",
    "Дата архівування",
    "Ід.код",
    "Найменування",
    "МФО",
]


def _sense_row(
    *,
    direction: str = "Кредит",
    amount: str = "125,50",
    purpose: str = "Оплата за послуги",
) -> list[str]:
    return [
        "26000000000001",
        "UA273000010000000000000000001",
        direction,
        "26000000000002",
        "UA753000010000000000000000010",
        "300001",
        "ТОВ Тестовий покупець",
        "11111111",
        purpose,
        "15.08.2026",
        "TEST-SENSE-001",
        amount,
        "UAH",
        "12:30:00",
        "15.08.2026",
        "15.08.2026",
        "0000000000",
        "ФОП Тестовий Тарас Іванович",
        "300001",
    ]


def _write_sense_statement(path: Path, rows: list[list[str]]) -> None:
    content = "\n".join(
        [
            ";".join(SENSE_HEADERS),
            *(";".join(row) for row in rows),
        ]
    )
    path.write_text(content, encoding="cp1251")


def test_parse_sense_file_parses_credit_and_debit(tmp_path: Path) -> None:
    path = tmp_path / "sense.csv"
    _write_sense_statement(
        path,
        [
            _sense_row(),
            _sense_row(direction="Дебет", amount="40,25"),
        ],
    )

    credit, debit = parse_sense_file(path)

    assert credit.bank is BankName.SENSE
    assert credit.credit == Decimal("125.50")
    assert credit.debit == Decimal("0.00")
    assert debit.credit == Decimal("0.00")
    assert debit.debit == Decimal("40.25")


def test_parse_sense_file_restores_unescaped_semicolons_in_purpose(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sense-with-semicolons.csv"
    purpose = "Оплата згідно договору; рахунок № 15; без ПДВ"
    _write_sense_statement(path, [_sense_row(purpose=purpose)])

    transaction = parse_sense_file(path)[0]

    assert transaction.payment_purpose == purpose
    assert transaction.document_number == "TEST-SENSE-001"


def test_parse_sense_file_rejects_missing_required_header(tmp_path: Path) -> None:
    path = tmp_path / "wrong-sense.csv"
    headers = [header for header in SENSE_HEADERS if header != "Наш IBAN"]
    path.write_text(";".join(headers), encoding="cp1251")

    with pytest.raises(MissingBankColumnError, match="Наш IBAN"):
        parse_sense_file(path)


@pytest.mark.parametrize(
    ("direction", "amount", "message"),
    [
        ("Невідомо", "10,00", "Операція.*unsupported transaction direction"),
        ("Кредит", "0,00", "Сума.*transaction amount must be positive"),
    ],
)
def test_parse_sense_file_rejects_invalid_transaction_values(
    tmp_path: Path,
    direction: str,
    amount: str,
    message: str,
) -> None:
    path = tmp_path / "invalid-sense.csv"
    _write_sense_statement(
        path,
        [_sense_row(direction=direction, amount=amount)],
    )

    with pytest.raises(InvalidBankRowError, match=message):
        parse_sense_file(path)
