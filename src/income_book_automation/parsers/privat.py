from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError

from income_book_automation.models import BankName, BankTransaction, TransactionSource
from income_book_automation.parsers.common import (
    open_bank_csv,
    parse_account_identifier,
    parse_decimal_value,
    parse_dotted_date,
    parse_ukrainian_iban,
    read_strict_csv_rows,
    require_non_blank_value,
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
    if amount == 0:
        raise InvalidBankRowError(
            f"File '{path.name}', row {row_number}, "
            "column 'Сума': transaction amount must be non-zero"
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

    account_number = parse_ukrainian_iban(
        row["Рахунок"],
        path,
        row_number,
        "Рахунок",
        required=True,
    )

    currency = require_non_blank_value(
        row["Валюта"],
        path,
        row_number,
        "Валюта",
    )

    document_number = row["Номер документу"].strip()

    counterparty = row["Кореспондент"].strip()
    counterparty_account = parse_account_identifier(
        row["Рахунок кореспондента"],
        path,
        row_number,
        "Рахунок кореспондента",
        required=False,
    )
    payment_purpose = row["Призначення платежу"].strip()

    counterparty_tax_id = row["ЄДРПОУ кореспондента"].strip() or None

    try:
        return BankTransaction(
            source=TransactionSource(
                original_filename=path.name,
                row_number=row_number,
            ),
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
        rows = read_strict_csv_rows(
            file,
            path=path,
            bank_name="PrivatBank",
            delimiter=";",
            required_headers=PRIVAT_REQUIRED_HEADERS,
        )

        return [parse_privat_row(row, path, row_number) for row_number, row in rows]
