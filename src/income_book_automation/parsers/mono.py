import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

from income_book_automation.models import BankName, BankTransaction


def normalize_header(value: str) -> str:
    return " ".join(value.split())


def parse_mono_date(value: str) -> date:
    day, month, year = map(int, value.strip().split("."))
    return date(year, month, day)


def parse_mono_row(
    row: dict[str, str],
    path: Path,
    row_number: int,
    *,
    account_number: str,
) -> BankTransaction:

    amount = abs(Decimal(row["Сума в валюті рахунку"].strip().replace(",", ".")))

    direction = row["Вид операції (дебет/кредит)"].strip()

    if direction == "Кредит":
        debit = Decimal(0)
        credit = amount
    elif direction == "Дебет":
        debit = amount
        credit = Decimal(0)
    else:
        raise ValueError(f"Unknown Mono transaction direction: {direction!r}")

    transaction_date = parse_mono_date(row["Дата операції"])

    currency = row["Валюта операції"].strip()

    document_number = row["Номер платіжного доручення"].strip()

    counterparty = row["Контрагент"].strip()
    counterparty_account = row["IBAN контрагента"].strip()
    payment_purpose = row["Деталі операції"].strip()

    counterparty_tax_id = row["ЄДРПОУ контрагента"].strip() or None

    return BankTransaction(
        date=transaction_date,
        bank=BankName.MONO,
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


def parse_mono_file(
    path: Path,
    *,
    account_number: str,
) -> list[BankTransaction]:
    transactions: list[BankTransaction] = []

    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file, delimiter=";")

        for row_number, raw_row in enumerate(reader, start=2):
            row = {
                normalize_header(key): value
                for key, value in raw_row.items()
                if key is not None
            }

            transactions.append(
                parse_mono_row(
                    row,
                    path,
                    row_number,
                    account_number=account_number,
                )
            )

    return transactions
