import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

from income_book_automation.parsers.mono import parse_mono_file, parse_mono_row

from income_book_automation.models import BankName

TEST_ACCOUNT = "UA000000000000000000000000001"


def _mono_row() -> dict[str, str]:
    return {
        "Дата операції": "07.07.2026",
        "Час операції": "12:30:00",
        "Вид операції (дебет/кредит)": "Кредит",
        "Деталі операції": "Оплата за тестові послуги",
        "Контрагент": "ТОВ Тестовий клієнт",
        "ЄДРПОУ контрагента": "0000000000",
        "IBAN контрагента": "UA000000000000000000000000002",
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
    assert transaction.counterparty_account == "UA000000000000000000000000002"
    assert transaction.counterparty_tax_id == "0000000000"


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
