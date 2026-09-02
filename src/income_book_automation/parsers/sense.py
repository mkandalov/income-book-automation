import csv
from collections import Counter
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import TextIO

from pydantic import ValidationError

from income_book_automation.models import BankName, BankTransaction, TransactionSource
from income_book_automation.parsers.common import (
    open_bank_csv,
    parse_decimal_value,
    parse_dotted_date,
    parse_ukrainian_iban,
    require_non_blank_value,
    validate_required_headers,
)
from income_book_automation.parsers.errors import (
    BankStatementFormatError,
    DuplicateBankColumnError,
    EmptyBankStatementError,
    InvalidBankRowError,
    InvalidBankRowStructureError,
)

SENSE_REQUIRED_HEADERS = {
    "Наш рахунок",
    "Наш IBAN",
    "Операція",
    "Рахунок",
    "IBAN",
    "МФО банку контрагента",
    "Найменування контрагента",
    "Код контрагента",
    "Призначення платежу",
    "Дата проведення",
    "Номер документа",
    "Сума",
    "Валюта",
    "Час проведення",
    "Дата документа",
    "Дата архівування",
    "Ід.код",
    "Найменування",
    "МФО",
}

PURPOSE_HEADER = "Призначення платежу"


def _read_sense_rows(
    file: TextIO,
    *,
    path: Path,
) -> Iterator[tuple[int, dict[str, str]]]:
    reader = csv.reader(file, delimiter=";")
    raw_headers = next(reader, None)
    location = f"File '{path.name}', bank 'Sense Bank'"

    if raw_headers is None:
        raise BankStatementFormatError(f"{location}: CSV header row is missing")

    headers = [header.strip().lstrip("\ufeff") for header in raw_headers]
    duplicate_headers = sorted(
        header for header, count in Counter(headers).items() if count > 1
    )
    if duplicate_headers:
        formatted = ", ".join(
            f"'{header or '<blank>'}'" for header in duplicate_headers
        )
        raise DuplicateBankColumnError(
            f"{location}, row 1: duplicate CSV columns: {formatted}"
        )

    validate_required_headers(headers, SENSE_REQUIRED_HEADERS, path)

    purpose_index = headers.index(PURPOSE_HEADER)
    expected_column_count = len(headers)
    trailing_column_count = expected_column_count - purpose_index - 1
    has_transaction_rows = False

    for row_number, values in enumerate(reader, start=2):
        if all(not value.strip() for value in values):
            continue

        has_transaction_rows = True
        if len(values) < expected_column_count:
            raise InvalidBankRowStructureError(
                f"{location}, row {row_number}: expected at least "
                f"{expected_column_count} columns, got {len(values)}"
            )

        purpose_end = len(values) - trailing_column_count
        reconstructed_values = [
            *values[:purpose_index],
            ";".join(values[purpose_index:purpose_end]),
            *values[purpose_end:],
        ]
        if len(reconstructed_values) != expected_column_count:
            raise InvalidBankRowStructureError(
                f"{location}, row {row_number}: could not reconstruct "
                "the payment-purpose column"
            )

        yield row_number, dict(zip(headers, reconstructed_values, strict=True))

    if not has_transaction_rows:
        raise EmptyBankStatementError(
            f"{location}: statement contains no transaction rows"
        )


def parse_sense_row(
    row: dict[str, str],
    path: Path,
    row_number: int,
) -> BankTransaction:
    amount = parse_decimal_value(row["Сума"], path, row_number, "Сума")
    if amount <= 0:
        raise InvalidBankRowError(
            f"File '{path.name}', row {row_number}, column 'Сума': "
            "transaction amount must be positive"
        )

    direction = require_non_blank_value(
        row["Операція"],
        path,
        row_number,
        "Операція",
    )
    if direction == "Кредит":
        debit = Decimal(0)
        credit = amount
    elif direction == "Дебет":
        debit = amount
        credit = Decimal(0)
    else:
        raise InvalidBankRowError(
            f"File '{path.name}', row {row_number}, column 'Операція': "
            "unsupported transaction direction"
        )

    try:
        return BankTransaction(
            source=TransactionSource(
                original_filename=path.name,
                row_number=row_number,
            ),
            date=parse_dotted_date(
                row["Дата проведення"],
                path,
                row_number,
                "Дата проведення",
                order="DMY",
            ),
            bank=BankName.SENSE,
            account_number=parse_ukrainian_iban(
                row["Наш IBAN"],
                path,
                row_number,
                "Наш IBAN",
                required=True,
            ),
            currency=require_non_blank_value(
                row["Валюта"],
                path,
                row_number,
                "Валюта",
            ),
            document_number=row["Номер документа"].strip(),
            debit=debit,
            credit=credit,
            counterparty=row["Найменування контрагента"].strip(),
            counterparty_account=parse_ukrainian_iban(
                row["IBAN"],
                path,
                row_number,
                "IBAN",
                required=False,
            ),
            counterparty_tax_id=row["Код контрагента"].strip() or None,
            payment_purpose=row[PURPOSE_HEADER].strip(),
        )
    except ValidationError as error:
        raise InvalidBankRowError(
            f"File '{path.name}', row {row_number}: invalid transaction values"
        ) from error


def parse_sense_file(path: Path) -> list[BankTransaction]:
    with open_bank_csv(path, encoding="cp1251") as file:
        return [
            parse_sense_row(row, path, row_number)
            for row_number, row in _read_sense_rows(file, path=path)
        ]
