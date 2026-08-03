import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

from income_book_automation.models import BankName, BankTransaction


def parse_privat_date(value: str) -> date:
    day, month, year = map(int, value.strip().split("."))
    return date(year, month, day)


def parse_privat_row(
    row: dict[str, str],
    path: Path,
    row_number: int,
) -> BankTransaction:
    normalized_amount = (
        row["Сума"].strip().replace(" ", "").replace("\u00a0", "").replace(",", ".")
    )

    amount = Decimal(normalized_amount)

    if amount > 0:
        debit = Decimal(0)
        credit = amount
    else:
        debit = abs(amount)
        credit = Decimal(0)

    transaction_date = parse_privat_date(row["Дата операції"])

    account_number = row["Рахунок"].strip()
    currency = row["Валюта"].strip()

    document_number = row["Номер документу"].strip()

    counterparty = row["Кореспондент"].strip()
    counterparty_account = row["Рахунок кореспондента"].strip()
    payment_purpose = row["Призначення платежу"].strip()

    counterparty_tax_id = row["ЄДРПОУ кореспондента"].strip() or None

    return BankTransaction(
        date=transaction_date,
        bank=BankName.PRIVAT,
        account_number=account_number,
        currency=currency,
        document_number=document_number,
        debit=debit,
        credit=credit,
        counterparty=counterparty,
        counterparty_account=counterparty_account,
        payment_purpose=payment_purpose,
        counterparty_tax_id=counterparty_tax_id,
    )


def parse_privat_file(path: Path) -> list[BankTransaction]:
    with path.open(encoding="cp1251", newline="") as file:
        reader = csv.DictReader(file, delimiter=";")

        return [
            parse_privat_row(row, path, row_number)
            for row_number, row in enumerate(reader, start=2)
        ]
