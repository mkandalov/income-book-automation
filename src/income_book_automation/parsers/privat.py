import csv
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError

from income_book_automation.models import BankName, BankTransaction
from income_book_automation.parsers.common import (
    open_bank_csv,
    parse_decimal_value,
    parse_dotted_date,
    validate_required_headers,
)
from income_book_automation.parsers.errors import InvalidBankRowError

PRIVAT_REQUIRED_HEADERS = {
    "Дата операції",
    "Рахунок",
    "Валюта",
    "Номер документу",
    "Сума",
    "Кореспондент",
    "Рахунок кореспондента",
    "ЄДРПОУ кореспондента",
    "Призначення платежу",
}


def parse_privat_row(
    row: dict[str, str],
    path: Path,
    row_number: int,
) -> BankTransaction:
    amount = parse_decimal_value(
        row["Сума"],
        path,
        row_number,
        "Сума",
    )

    if amount > 0:
        debit = Decimal(0)
        credit = amount
    else:
        debit = abs(amount)
        credit = Decimal(0)

    transaction_date = parse_dotted_date(
        row["Дата операції"],
        path,
        row_number,
        "Дата операції",
        order="DMY",
    )

    account_number = row["Рахунок"].strip()
    currency = row["Валюта"].strip()

    document_number = row["Номер документу"].strip()

    counterparty = row["Кореспондент"].strip()
    counterparty_account = row["Рахунок кореспондента"].strip()
    payment_purpose = row["Призначення платежу"].strip()

    counterparty_tax_id = row["ЄДРПОУ кореспондента"].strip() or None

    try:
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
    except ValidationError as error:
        raise InvalidBankRowError(
            f"File '{path.name}', row {row_number}: invalid transaction values"
        ) from error


def parse_privat_file(path: Path) -> list[BankTransaction]:
    with open_bank_csv(path, encoding="cp1251") as file:
        reader = csv.DictReader(file, delimiter=";")

        validate_required_headers(
            reader.fieldnames,
            PRIVAT_REQUIRED_HEADERS,
            path,
        )

        return [
            parse_privat_row(row, path, row_number)
            for row_number, row in enumerate(reader, start=2)
        ]
