import csv
import hashlib
from decimal import Decimal
from io import StringIO
from pathlib import Path
from typing import TextIO

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
from income_book_automation.parsers.errors import (
    BankStatementFormatError,
    InvalidBankRowError,
)

MONO_REQUIRED_HEADERS = {
    "Дата операції",
    "Вид операції (дебет/кредит)",
    "Сума в валюті рахунку",
    "Валюта операції",
    "Контрагент",
    "IBAN контрагента",
    "ЄДРПОУ контрагента",
    "Деталі операції",
}

MONO_HEADER_ANCHORS = {
    "Дата операції",
    "Вид операції (дебет/кредит)",
    "Сума в валюті рахунку",
}

MONO_DOCUMENT_NUMBER_HEADER = "Номер платіжного доручення"
MONO_DELIMITERS = (";", ",")
MONO_HEADER_SCAN_LIMIT = 5


def normalize_header(value: str) -> str:
    return " ".join(value.split())


def detect_mono_csv_layout(file: TextIO, path: Path) -> tuple[str, int]:
    """Find the delimiter and logical header row for supported Mono exports."""
    sample = file.read(65_536)
    file.seek(0)

    for delimiter in MONO_DELIMITERS:
        try:
            reader = csv.reader(StringIO(sample), delimiter=delimiter)

            for row_number, row in enumerate(reader, start=1):
                headers = {normalize_header(value) for value in row if value.strip()}

                if MONO_HEADER_ANCHORS.issubset(headers):
                    return delimiter, row_number

                if row_number >= MONO_HEADER_SCAN_LIMIT:
                    break
        except csv.Error:
            continue

    raise BankStatementFormatError(
        f"File '{path.name}', bank 'Monobank': CSV header row was not recognized"
    )


def build_generated_document_number(
    row: dict[str, str],
    *,
    account_number: str,
) -> str:
    """Build a stable identifier when a Mono export omits a document number."""
    identifying_values = (
        account_number,
        row.get("Дата операції", ""),
        row.get("Час операції", ""),
        row.get("Вид операції (дебет/кредит)", ""),
        row.get("Сума в валюті рахунку", ""),
        row.get("Валюта операції", ""),
        row.get("Контрагент", ""),
        row.get("ЄДРПОУ контрагента", ""),
        row.get("IBAN контрагента", ""),
        row.get("Деталі операції", ""),
        row.get("Залишок після операції в валюті рахунку", ""),
    )
    normalized_values = (
        " ".join(value.casefold().split()) for value in identifying_values
    )
    digest = hashlib.sha256("\x1f".join(normalized_values).encode()).hexdigest()
    return f"MONO-{digest[:24].upper()}"


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
    ).casefold()

    if direction == "кредит":
        if signed_amount <= 0:
            raise InvalidBankRowError(
                f"File '{path.name}', row {row_number}, "
                "column 'Сума в валюті рахунку': "
                "credit transaction amount must be positive"
            )

        debit = Decimal(0)
        credit = signed_amount

    elif direction == "дебет":
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

    document_number = row.get(MONO_DOCUMENT_NUMBER_HEADER, "").strip()
    if not document_number:
        document_number = build_generated_document_number(
            row,
            account_number=account_number,
        )

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
        delimiter, header_row_number = detect_mono_csv_layout(file, path)
        rows = read_strict_csv_rows(
            file,
            path=path,
            bank_name="Monobank",
            delimiter=delimiter,
            required_headers=MONO_REQUIRED_HEADERS,
            header_row_number=header_row_number,
            rows_before_header=header_row_number - 1,
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
