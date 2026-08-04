import csv
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

PUMB_CURRENCY_CODES = {
    "980": "UAH",
    "978": "EUR",
    "840": "USD",
}

PUMB_REQUIRED_HEADERS = {
    "ST_DATE",
    "ACC_NUMB",
    "CUR_NUMB",
    "DOC_NO",
    "DB",
    "CR",
    "KOR_NAME",
    "KOR_ACC",
    "KOR_OKPO",
    "DESCRIPT",
}


def parse_pumb_row(row: dict[str, str], path: Path, row_number: int) -> BankTransaction:
    transaction_date = parse_dotted_date(
        row["ST_DATE"],
        path,
        row_number,
        "ST_DATE",
        order="YMD",
    )
    account_number = row["ACC_NUMB"].strip()

    currency_code = row["CUR_NUMB"].strip()
    try:
        currency = PUMB_CURRENCY_CODES[currency_code]
    except KeyError as error:
        raise InvalidBankRowError(
            f"File '{path.name}', row {row_number}, "
            "column 'CUR_NUMB': unsupported currency code"
        ) from error

    document_number = row["DOC_NO"].strip()

    debit = parse_decimal_value(
        row["DB"],
        path,
        row_number,
        "DB",
    )
    credit = parse_decimal_value(
        row["CR"],
        path,
        row_number,
        "CR",
    )

    counterparty = row["KOR_NAME"].strip()
    counterparty_account = row["KOR_ACC"].strip()
    payment_purpose = row["DESCRIPT"].strip()

    counterparty_tax_id = row["KOR_OKPO"].strip() or None
    try:
        return BankTransaction(
            date=transaction_date,
            bank=BankName.PUMB,
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


def parse_pumb_file(path: Path) -> list[BankTransaction]:
    with open_bank_csv(path, encoding="cp1251") as file:
        reader = csv.DictReader(file, delimiter=";")

        validate_required_headers(
            reader.fieldnames,
            PUMB_REQUIRED_HEADERS,
            path,
        )

        return [
            parse_pumb_row(row, path, row_number)
            for row_number, row in enumerate(reader, start=2)
        ]
