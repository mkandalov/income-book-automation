import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

from income_book_automation.models import BankName, BankTransaction

PUMB_CURRENCY_CODES = {
    "980": "UAH",
    "978": "EUR",
    "840": "USD",
}


def parse_pumb_row(row: dict[str, str], path: Path, row_number: int) -> BankTransaction:
    transaction_date = date.fromisoformat(row["ST_DATE"].strip().replace(".", "-"))
    account_number = row["ACC_NUMB"].strip()
    currency = PUMB_CURRENCY_CODES[row["CUR_NUMB"].strip()]
    document_number = row["DOC_NO"].strip()

    debit = Decimal(row["DB"].strip().replace(",", "."))
    credit = Decimal(row["CR"].strip().replace(",", "."))

    counterparty = row["KOR_NAME"].strip()
    counterparty_account = row["KOR_ACC"].strip()
    payment_purpose = row["DESCRIPT"].strip()

    counterparty_tax_id = row["KOR_OKPO"].strip() or None

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


def parse_pumb_file(path: Path) -> list[BankTransaction]:
    with path.open(encoding="cp1251", newline="") as file:
        reader = csv.DictReader(file, delimiter=";")

        return [
            parse_pumb_row(row, path, row_number)
            for row_number, row in enumerate(reader, start=2)
        ]
