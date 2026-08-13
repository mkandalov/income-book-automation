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
    account_number = parse_ukrainian_iban(
        row["ACC_NUMB"],
        path,
        row_number,
        "ACC_NUMB",
        required=True,
    )

    currency_code = require_non_blank_value(
        row["CUR_NUMB"],
        path,
        row_number,
        "CUR_NUMB",
    )
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
    counterparty_account = parse_account_identifier(
        row["KOR_ACC"],
        path,
        row_number,
        "KOR_ACC",
        required=False,
    )
    payment_purpose = row["DESCRIPT"].strip()

    counterparty_tax_id = row["KOR_OKPO"].strip() or None
    try:
        return BankTransaction(
            source=TransactionSource(
                original_filename=path.name,
                row_number=row_number,
            ),
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
        rows = read_strict_csv_rows(
            file,
            path=path,
            bank_name="PUMB",
            delimiter=";",
            required_headers=PUMB_REQUIRED_HEADERS,
        )

        return [parse_pumb_row(row, path, row_number) for row_number, row in rows]
