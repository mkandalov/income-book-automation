import csv
import re
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
from income_book_automation.parsers.mono import parse_mono_file, parse_mono_row

TEST_ACCOUNT = "UA273000010000000000000000001"


def _mono_row() -> dict[str, str]:
    return {
        "Дата операції": "07.07.2026",
        "Час операції": "12:30:00",
        "Вид операції (дебет/кредит)": "Кредит",
        "Деталі операції": "Оплата за тестові послуги",
        "Контрагент": "ТОВ Тестовий клієнт",
        "ЄДРПОУ контрагента": "0000000000",
        "IBAN контрагента": "UA973000010000000000000000002",
        "Сума в валюті рахунку": "100.00",
        "Сума в валюті операції": "100.00",
        "Валюта операції": "UAH",
        "Курс": "1.00",
        "Еквівалент суми за курсом НБУ на дату операції (для зарахувань)": "100.00",
        "Сума комісій в валюті рахунку": "0.00",
        "Залишок після операції в валюті рахунку": "100.00",
        "Номер платіжного доручення": "TEST-DOC-001",
        "Фактичний платник": "ТОВ Тестовий клієнт",
        "Ідентифікатор фактичного платника": "0000000000",
    }


def test_parse_mono_row_maps_credit_transaction() -> None:
    transaction = parse_mono_row(
        _mono_row(),
        Path("synthetic-mono.csv"),
        2,
        account_number=TEST_ACCOUNT,
    )

    assert transaction.date == date(2026, 7, 7)
    assert transaction.bank is BankName.MONO
    assert transaction.account_number == TEST_ACCOUNT
    assert transaction.currency == "UAH"
    assert transaction.debit == Decimal("0.00")
    assert transaction.credit == Decimal("100.00")
    assert transaction.counterparty == "ТОВ Тестовий клієнт"
    assert transaction.counterparty_account == "UA973000010000000000000000002"
    assert transaction.counterparty_tax_id == "0000000000"
    assert transaction.source.original_filename == "synthetic-mono.csv"
    assert transaction.source.row_number == 2


@pytest.mark.parametrize(
    ("column_name", "overrides"),
    [
        ("Валюта операції", {"Валюта операції": "   "}),
        (
            "Вид операції (дебет/кредит)",
            {"Вид операції (дебет/кредит)": ""},
        ),
    ],
)
def test_parse_mono_row_rejects_missing_technical_value(
    column_name: str,
    overrides: dict[str, str],
) -> None:
    row = _mono_row()
    row.update(overrides)

    with pytest.raises(
        InvalidBankRowError,
        match=rf"column '{re.escape(column_name)}': required value is missing",
    ):
        parse_mono_row(
            row,
            Path("synthetic-mono.csv"),
            7,
            account_number=TEST_ACCOUNT,
        )


def test_parse_mono_row_rejects_missing_statement_account() -> None:
    with pytest.raises(
        InvalidBankRowError,
        match="column 'statement account': required value is missing",
    ):
        parse_mono_row(
            _mono_row(),
            Path("synthetic-mono.csv"),
            7,
            account_number="   ",
        )


@pytest.mark.parametrize(
    ("direction", "amount", "message"),
    [
        ("Кредит", "-10.00", "credit transaction amount must be positive"),
        ("Дебет", "10.00", "debit transaction amount must be negative"),
        ("Кредит", "0.00", "credit transaction amount must be positive"),
        ("Дебет", "0.00", "debit transaction amount must be negative"),
    ],
)
def test_parse_mono_row_rejects_inconsistent_amount_sign(
    direction: str,
    amount: str,
    message: str,
) -> None:
    row = _mono_row()
    row["Вид операції (дебет/кредит)"] = direction
    row["Сума в валюті рахунку"] = amount

    with pytest.raises(InvalidBankRowError, match=message):
        parse_mono_row(
            row,
            Path("synthetic-mono.csv"),
            7,
            account_number=TEST_ACCOUNT,
        )


def test_parse_mono_file_normalizes_headers_and_direction(tmp_path: Path) -> None:
    credit_row = _mono_row()
    debit_row = _mono_row()
    debit_row["Дата операції"] = "08.07.2026"
    debit_row["Вид операції (дебет/кредит)"] = "Дебет"
    debit_row["Сума в валюті рахунку"] = "-25.00"
    debit_row["Номер платіжного доручення"] = "TEST-DOC-002"

    file_headers = {header: header.replace(" ", " \n", 1) for header in credit_row}
    source_path = tmp_path / "synthetic-mono.csv"

    with source_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=file_headers.values(),
            delimiter=";",
        )
        writer.writeheader()
        for row in (credit_row, debit_row):
            writer.writerow({file_headers[key]: value for key, value in row.items()})

    transactions = parse_mono_file(
        source_path,
        account_number=TEST_ACCOUNT,
    )

    assert len(transactions) == 2
    assert transactions[0].credit == Decimal("100.00")
    assert transactions[1].debit == Decimal("25.00")
    assert transactions[1].credit == Decimal("0.00")
    assert transactions[1].date == date(2026, 7, 8)


def test_parse_mono_file_supports_comma_export_with_metadata(tmp_path: Path) -> None:
    headers = [
        "Дата операції",
        "Час операції",
        "Вид операції (дебет/кредит)",
        "Деталі операції",
        "Контрагент",
        "ЄДРПОУ контрагента",
        "IBAN контрагента",
        "Сума в валюті рахунку",
        "Сума в валюті операції",
        "Валюта операції",
        "Курс",
        "Еквівалент суми за курсом НБУ на дату операції (для зарахувань)",
        "Сума комісій в валюті рахунку",
        "Залишок після операції в валюті рахунку",
    ]
    credit_values = [
        "07.07.2026",
        "12:30:00",
        "кредит",
        "Оплата за тестові послуги",
        "ТОВ Тестовий клієнт",
        "0000000000",
        "UA973000010000000000000000002",
        "100.00",
        "100.00",
        "UAH",
        "-",
        "-",
        "-",
        "100.00",
    ]
    debit_values = credit_values.copy()
    debit_values[0] = "08.07.2026"
    debit_values[1] = "13:30:00"
    debit_values[2] = "дебет"
    debit_values[7] = "-25.00"
    debit_values[8] = "-25.00"
    debit_values[13] = "75.00"

    source_path = tmp_path / "comma-export-mono.csv"
    with source_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file, delimiter=",")
        writer.writerow(
            [
                (
                    "ФОП Тестовий, Виписка за рахунком "
                    f"{TEST_ACCOUNT} за період з 01.07.2026 по 31.07.2026"
                )
            ]
        )
        writer.writerow([header.replace(" ", " \n", 1) for header in headers])
        writer.writerow(credit_values)
        writer.writerow(debit_values)

    transactions = parse_mono_file(source_path, account_number=TEST_ACCOUNT)

    assert len(transactions) == 2
    assert transactions[0].source.row_number == 3
    assert transactions[0].credit == Decimal("100.00")
    assert transactions[0].document_number.startswith("MONO-")
    assert transactions[1].source.row_number == 4
    assert transactions[1].debit == Decimal("25.00")
    assert transactions[1].document_number.startswith("MONO-")
    assert transactions[0].document_number != transactions[1].document_number


def test_parse_mono_file_rejects_missing_required_header(
    tmp_path: Path,
) -> None:
    row = _mono_row()
    del row["Деталі операції"]

    source_path = tmp_path / "missing-header-mono.csv"
    with source_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=row.keys(), delimiter=";")
        writer.writeheader()
        writer.writerow(row)

    with pytest.raises(MissingBankColumnError, match="Деталі операції"):
        parse_mono_file(source_path, account_number=TEST_ACCOUNT)


@pytest.mark.parametrize(
    ("extra_values", "actual_column_count"),
    [
        (-1, 16),
        (1, 18),
    ],
)
def test_parse_mono_file_rejects_wrong_row_width(
    tmp_path: Path,
    extra_values: int,
    actual_column_count: int,
) -> None:
    row = _mono_row()
    values = list(row.values())

    if extra_values < 0:
        values = values[:extra_values]
    else:
        values.extend(["UNEXPECTED"] * extra_values)

    source_path = tmp_path / "damaged-mono.csv"
    with source_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file, delimiter=";")
        writer.writerow(row.keys())
        writer.writerow(values)

    with pytest.raises(
        InvalidBankRowStructureError,
        match=(
            "File 'damaged-mono.csv', bank 'Monobank', row 2: "
            f"expected 17 columns, got {actual_column_count}"
        ),
    ):
        parse_mono_file(source_path, account_number=TEST_ACCOUNT)


def test_parse_mono_file_rejects_header_without_transactions(
    tmp_path: Path,
) -> None:
    row = _mono_row()
    source_path = tmp_path / "header-only-mono.csv"

    with source_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file, delimiter=";")
        writer.writerow(row.keys())

    with pytest.raises(
        EmptyBankStatementError,
        match="statement contains no transaction rows",
    ):
        parse_mono_file(source_path, account_number=TEST_ACCOUNT)


def test_parse_mono_row_wraps_unknown_direction() -> None:
    row = _mono_row()
    row["Вид операції (дебет/кредит)"] = "Unknown"

    with pytest.raises(
        InvalidBankRowError,
        match=(
            r"row 7, column 'Вид операції \(дебет/кредит\)': "
            "unsupported transaction direction"
        ),
    ):
        parse_mono_row(
            row,
            Path("synthetic-mono.csv"),
            7,
            account_number=TEST_ACCOUNT,
        )


def test_parse_mono_file_wraps_missing_file(tmp_path: Path) -> None:
    source_path = tmp_path / "missing-mono.csv"

    with pytest.raises(BankStatementReadError, match="missing-mono.csv"):
        parse_mono_file(source_path, account_number=TEST_ACCOUNT)


def test_parse_mono_row_rejects_invalid_statement_iban() -> None:
    with pytest.raises(
        InvalidBankRowError,
        match="column 'statement account': invalid Ukrainian IBAN",
    ):
        parse_mono_row(
            _mono_row(),
            Path("synthetic-mono.csv"),
            7,
            account_number="UA003000010000000000000000001",
        )


def test_parse_mono_row_rejects_invalid_counterparty_iban() -> None:
    row = _mono_row()
    row["IBAN контрагента"] = "UA003000010000000000000000001"

    with pytest.raises(
        InvalidBankRowError,
        match="IBAN контрагента': invalid Ukrainian IBAN",
    ):
        parse_mono_row(
            row,
            Path("synthetic-mono.csv"),
            7,
            account_number=TEST_ACCOUNT,
        )
