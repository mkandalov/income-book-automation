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

MONO_REQUIRED_HEADERS = {
    "Дата операції",
    "Вид операції (дебет/кредит)",
    "Сума в валюті рахунку",
    "Валюта операції",
    "Номер платіжного доручення",
    "Контрагент",
    "IBAN контрагента",
    "ЄДРПОУ контрагента",
    "Деталі операції",
}


def normalize_header(value: str) -> str:
    return " ".join(value.split())


def parse_mono_row(
    row: dict[str, str],
    path: Path,
    row_number: int,
    *,
    account_number: str,
) -> BankTransaction:

    amount = abs(
        parse_decimal_value(
            row["Сума в валюті рахунку"],
            path,
            row_number,
            "Сума в валюті рахунку",
        )
    )

    direction = row["Вид операції (дебет/кредит)"].strip()

    if direction == "Кредит":
        debit = Decimal(0)
        credit = amount
    elif direction == "Дебет":
        debit = amount
        credit = Decimal(0)
    else:
        raise InvalidBankRowError(
            f"File '{path.name}', row {row_number}, "
            "column 'Вид операції (дебет/кредит)': "
            "unsupported transaction direction"
        )

    transaction_date = parse_dotted_date(
        row["Дата операції"],
        path,
        row_number,
        "Дата операції",
        order="DMY",
    )

    currency = row["Валюта операції"].strip()

    document_number = row["Номер платіжного доручення"].strip()

    counterparty = row["Контрагент"].strip()
    counterparty_account = row["IBAN контрагента"].strip()
    payment_purpose = row["Деталі операції"].strip()

    counterparty_tax_id = row["ЄДРПОУ контрагента"].strip() or None

    try:
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
    except ValidationError as error:
        raise InvalidBankRowError(
            f"File '{path.name}', row {row_number}: invalid transaction values"
        ) from error


def parse_mono_file(
    path: Path,
    *,
    account_number: str,
) -> list[BankTransaction]:
    transactions: list[BankTransaction] = []

    with open_bank_csv(path, encoding="utf-8-sig") as file:
        reader = csv.DictReader(file, delimiter=";")

        raw_fieldnames = reader.fieldnames

        normalized_fieldnames = (
            None
            if raw_fieldnames is None
            else [
                normalize_header(header)
                for header in raw_fieldnames
                if header is not None
            ]
        )

        validate_required_headers(
            normalized_fieldnames,
            MONO_REQUIRED_HEADERS,
            path,
        )

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
