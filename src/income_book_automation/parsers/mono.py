from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError

from income_book_automation.models import BankName, BankTransaction, TransactionSource
from income_book_automation.parsers.common import (
    open_bank_csv,
    parse_decimal_value,
    parse_dotted_date,
    parse_ukrainian_iban,
    read_strict_csv_rows,
    require_non_blank_value,
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

    signed_amount = parse_decimal_value(
        row["Сума в валюті рахунку"],
        path,
        row_number,
        "Сума в валюті рахунку",
    )
    account_number = parse_ukrainian_iban(
        account_number,
        path,
        row_number,
        "statement account",
        required=True,
    )
    direction = require_non_blank_value(
        row["Вид операції (дебет/кредит)"],
        path,
        row_number,
        "Вид операції (дебет/кредит)",
    )

    if direction == "Кредит":
        if signed_amount <= 0:
            raise InvalidBankRowError(
                f"File '{path.name}', row {row_number}, "
                "column 'Сума в валюті рахунку': "
                "credit transaction amount must be positive"
            )

        debit = Decimal(0)
        credit = signed_amount

    elif direction == "Дебет":
        if signed_amount >= 0:
            raise InvalidBankRowError(
                f"File '{path.name}', row {row_number}, "
                "column 'Сума в валюті рахунку': "
                "debit transaction amount must be negative"
            )

        debit = abs(signed_amount)
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

    currency = require_non_blank_value(
        row["Валюта операції"],
        path,
        row_number,
        "Валюта операції",
    )

    document_number = row["Номер платіжного доручення"].strip()

    counterparty = row["Контрагент"].strip()
    counterparty_account = parse_ukrainian_iban(
        row["IBAN контрагента"],
        path,
        row_number,
        "IBAN контрагента",
        required=False,
    )
    payment_purpose = row["Деталі операції"].strip()

    counterparty_tax_id = row["ЄДРПОУ контрагента"].strip() or None

    try:
        return BankTransaction(
            source=TransactionSource(
                original_filename=path.name,
                row_number=row_number,
            ),
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
    with open_bank_csv(path, encoding="utf-8-sig") as file:
        rows = read_strict_csv_rows(
            file,
            path=path,
            bank_name="Monobank",
            delimiter=";",
            required_headers=MONO_REQUIRED_HEADERS,
            normalize_header=normalize_header,
        )

        return [
            parse_mono_row(
                row,
                path,
                row_number,
                account_number=account_number,
            )
            for row_number, row in rows
        ]
