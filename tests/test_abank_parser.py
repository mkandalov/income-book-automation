import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from income_book_automation.models import BankName
from income_book_automation.parsers.abank import (
    parse_abank_file,
    parse_abank_metadata,
    parse_abank_row,
)
from income_book_automation.parsers.errors import (
    BankStatementFormatError,
    BankStatementReadError,
    InvalidBankRowError,
    MissingBankColumnError,
)

TEST_ACCOUNT = "UA000000000000000000000000001"
TEST_COUNTERPARTY_ACCOUNT = "UA000000000000000000000000002"
TEST_METADATA = (
    "Виписка за рахунком ФОП ТЕСТОВИЙ ТАРАС ІВАНОВИЧ "
    f"{TEST_ACCOUNT} UAH за період з 01.07.2026-31.07.2026"
)


def _abank_row() -> dict[str, str]:
    return {
        "Дата операції": "07.07.2026",
        "Час операції": "12:30:00",
        "№ платежу": "TEST-DOC-001",
        "Тип операції": "Вхідна",
        "Контрагент": "ТОВ Тестовий клієнт",
        "ЄДРПОУ/РНОКПП контрагента": "0000000000",
        "IBAN Контрагента": TEST_COUNTERPARTY_ACCOUNT,
        "Призначення платежу": "Оплата за тестові послуги",
        "Сума, грн": "100,00",
        "Залишок після операції в валюті рахунку": "150,00",
    }


def _write_abank_file(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        file.write(f"{TEST_METADATA}\n")
        writer = csv.DictWriter(
            file,
            fieldnames=_abank_row().keys(),
            delimiter=",",
        )
        writer.writeheader()
        writer.writerows(rows)


def test_parse_abank_metadata_extracts_account_and_currency() -> None:
    account_number, currency = parse_abank_metadata(
        TEST_METADATA,
        Path("synthetic-abank.csv"),
    )

    assert account_number == TEST_ACCOUNT
    assert currency == "UAH"


def test_parse_abank_row_maps_incoming_transaction() -> None:
    transaction = parse_abank_row(
        _abank_row(),
        Path("synthetic-abank.csv"),
        3,
        account_number=TEST_ACCOUNT,
        currency="UAH",
    )

    assert transaction.date == date(2026, 7, 7)
    assert transaction.bank is BankName.ABANK
    assert transaction.account_number == TEST_ACCOUNT
    assert transaction.currency == "UAH"
    assert transaction.document_number == "TEST-DOC-001"
    assert transaction.debit == Decimal("0.00")
    assert transaction.credit == Decimal("100.00")
    assert transaction.counterparty == "ТОВ Тестовий клієнт"
    assert transaction.counterparty_account == TEST_COUNTERPARTY_ACCOUNT
    assert transaction.payment_purpose == "Оплата за тестові послуги"
    assert transaction.counterparty_tax_id == "0000000000"


def test_parse_abank_row_maps_outgoing_transaction() -> None:
    row = _abank_row()
    row["Тип операції"] = "Вихідна"
    row["Сума, грн"] = "-25,50"

    transaction = parse_abank_row(
        row,
        Path("synthetic-abank.csv"),
        3,
        account_number=TEST_ACCOUNT,
        currency="UAH",
    )

    assert transaction.debit == Decimal("25.50")
    assert transaction.credit == Decimal("0.00")


def test_parse_abank_row_converts_empty_tax_id_to_none() -> None:
    row = _abank_row()
    row["ЄДРПОУ/РНОКПП контрагента"] = ""

    transaction = parse_abank_row(
        row,
        Path("synthetic-abank.csv"),
        3,
        account_number=TEST_ACCOUNT,
        currency="UAH",
    )

    assert transaction.counterparty_tax_id is None


def test_parse_abank_file_skips_metadata_and_reads_rows(tmp_path: Path) -> None:
    incoming_row = _abank_row()
    outgoing_row = _abank_row()
    outgoing_row["Дата операції"] = "08.07.2026"
    outgoing_row["№ платежу"] = "TEST-DOC-002"
    outgoing_row["Тип операції"] = "Вихідна"
    outgoing_row["Сума, грн"] = "-25,00"

    source_path = tmp_path / "synthetic-abank.csv"
    _write_abank_file(source_path, [incoming_row, outgoing_row])

    transactions = parse_abank_file(source_path)

    assert len(transactions) == 2
    assert transactions[0].credit == Decimal("100.00")
    assert transactions[1].debit == Decimal("25.00")
    assert transactions[1].date == date(2026, 7, 8)


def test_parse_abank_file_rejects_missing_required_header(
    tmp_path: Path,
) -> None:
    row = _abank_row()
    del row["Сума, грн"]

    source_path = tmp_path / "missing-header-abank.csv"
    with source_path.open("w", encoding="utf-8-sig", newline="") as file:
        file.write(f"{TEST_METADATA}\n")
        writer = csv.DictWriter(file, fieldnames=row.keys(), delimiter=",")
        writer.writeheader()
        writer.writerow(row)

    with pytest.raises(MissingBankColumnError, match="Сума, грн"):
        parse_abank_file(source_path)


def test_parse_abank_file_rejects_invalid_metadata(tmp_path: Path) -> None:
    source_path = tmp_path / "invalid-metadata-abank.csv"
    source_path.write_text(
        "Виписка без реквізитів\nДата операції\n",
        encoding="utf-8-sig",
    )

    with pytest.raises(
        BankStatementFormatError,
        match="statement account or currency is missing",
    ):
        parse_abank_file(source_path)


def test_parse_abank_row_rejects_unknown_direction() -> None:
    row = _abank_row()
    row["Тип операції"] = "Невідома"

    with pytest.raises(
        InvalidBankRowError,
        match="row 7, column 'Тип операції': unsupported transaction direction",
    ):
        parse_abank_row(
            row,
            Path("synthetic-abank.csv"),
            7,
            account_number=TEST_ACCOUNT,
            currency="UAH",
        )


@pytest.mark.parametrize(
    ("direction", "amount", "message"),
    [
        ("Вхідна", "-10,00", "incoming transaction amount must be positive"),
        ("Вихідна", "10,00", "outgoing transaction amount must be negative"),
    ],
)
def test_parse_abank_row_rejects_inconsistent_amount_sign(
    direction: str,
    amount: str,
    message: str,
) -> None:
    row = _abank_row()
    row["Тип операції"] = direction
    row["Сума, грн"] = amount

    with pytest.raises(InvalidBankRowError, match=message):
        parse_abank_row(
            row,
            Path("synthetic-abank.csv"),
            7,
            account_number=TEST_ACCOUNT,
            currency="UAH",
        )


def test_parse_abank_file_rejects_empty_file(tmp_path: Path) -> None:
    source_path = tmp_path / "empty-abank.csv"
    source_path.write_text("", encoding="utf-8-sig")

    with pytest.raises(
        BankStatementFormatError,
        match="statement metadata row is missing",
    ):
        parse_abank_file(source_path)


def test_parse_abank_file_wraps_missing_file(tmp_path: Path) -> None:
    source_path = tmp_path / "missing-abank.csv"

    with pytest.raises(BankStatementReadError, match="missing-abank.csv"):
        parse_abank_file(source_path)
