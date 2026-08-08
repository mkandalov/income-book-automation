import csv
import re
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
from income_book_automation.parsers.errors import (
    BankStatementFormatError,
    InvalidBankRowError,
)

ABANK_REQUIRED_HEADERS = {
    "Дата операції",
    "№ платежу",
    "Тип операції",
    "Контрагент",
    "ЄДРПОУ/РНОКПП контрагента",
    "IBAN Контрагента",
    "Призначення платежу",
    "Сума, грн",
}

ABANK_METADATA_PATTERN = re.compile(
    r"\b(?P<account_number>UA\d{27})\s+"
    r"(?P<currency>[A-Z]{3})\s+за\s+період\b",
    re.IGNORECASE,
)


def parse_abank_metadata(metadata: str, path: Path) -> tuple[str, str]:
    match = ABANK_METADATA_PATTERN.search(metadata)
    if match is None:
        raise BankStatementFormatError(
            f"File '{path.name}': statement account or currency "
            "is missing from the metadata row"
        )

    return (
        match.group("account_number").upper(),
        match.group("currency").upper(),
    )


def parse_abank_row(
    row: dict[str, str],
    path: Path,
    row_number: int,
    *,
    account_number: str,
    currency: str,
) -> BankTransaction:
    signed_amount = parse_decimal_value(
        row["Сума, грн"],
        path,
        row_number,
        "Сума, грн",
    )

    direction = row["Тип операції"].strip()
    if direction == "Вхідна":
        if signed_amount <= 0:
            raise InvalidBankRowError(
                f"File '{path.name}', row {row_number}, column 'Сума, грн': "
                "incoming transaction amount must be positive"
            )
        debit = Decimal(0)
        credit = signed_amount
    elif direction == "Вихідна":
        if signed_amount >= 0:
            raise InvalidBankRowError(
                f"File '{path.name}', row {row_number}, column 'Сума, грн': "
                "outgoing transaction amount must be negative"
            )
        debit = abs(signed_amount)
        credit = Decimal(0)
    else:
        raise InvalidBankRowError(
            f"File '{path.name}', row {row_number}, column 'Тип операції': "
            "unsupported transaction direction"
        )

    transaction_date = parse_dotted_date(
        row["Дата операції"],
        path,
        row_number,
        "Дата операції",
        order="DMY",
    )

    counterparty_tax_id = row["ЄДРПОУ/РНОКПП контрагента"].strip() or None

    try:
        return BankTransaction(
            date=transaction_date,
            bank=BankName.ABANK,
            account_number=account_number,
            currency=currency,
            document_number=row["№ платежу"].strip(),
            debit=debit,
            credit=credit,
            counterparty=row["Контрагент"].strip(),
            counterparty_account=row["IBAN Контрагента"].strip(),
            payment_purpose=row["Призначення платежу"].strip(),
            counterparty_tax_id=counterparty_tax_id,
        )
    except ValidationError as error:
        raise InvalidBankRowError(
            f"File '{path.name}', row {row_number}: invalid transaction values"
        ) from error


def parse_abank_file(path: Path) -> list[BankTransaction]:
    with open_bank_csv(path, encoding="utf-8-sig") as file:
        try:
            metadata = next(file).strip()
        except StopIteration as error:
            raise BankStatementFormatError(
                f"File '{path.name}': statement metadata row is missing"
            ) from error

        account_number, currency = parse_abank_metadata(metadata, path)

        reader = csv.DictReader(file, delimiter=",")
        validate_required_headers(
            reader.fieldnames,
            ABANK_REQUIRED_HEADERS,
            path,
        )

        return [
            parse_abank_row(
                row,
                path,
                row_number,
                account_number=account_number,
                currency=currency,
            )
            for row_number, row in enumerate(reader, start=3)
        ]
