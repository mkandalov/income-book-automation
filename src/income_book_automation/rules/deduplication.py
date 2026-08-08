"""Detect duplicate bank transactions across statement files."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from income_book_automation.models import BankName, BankTransaction

type TransactionKey = tuple[
    BankName,
    str,
    str,
    date,
    str,
    Decimal,
    Decimal,
    str,
]


@dataclass(frozen=True, slots=True)
class TransactionDeduplicationResult:
    unique: tuple[BankTransaction, ...]
    duplicates: tuple[BankTransaction, ...]


def _normalize_account(value: str) -> str:
    return "".join(value.split()).upper()


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _transaction_key(
    transaction: BankTransaction,
) -> TransactionKey | None:
    document_number = _normalize_text(transaction.document_number)

    if not document_number:
        return None

    return (
        transaction.bank,
        _normalize_account(transaction.account_number),
        transaction.currency.upper(),
        transaction.date,
        document_number,
        transaction.debit,
        transaction.credit,
        _normalize_account(transaction.counterparty_account),
    )


def deduplicate_bank_transaction(
    transactions: list[BankTransaction],
) -> TransactionDeduplicationResult:
    seen_keys: set[TransactionKey] = set()

    unique: list[BankTransaction] = []
    duplicates: list[BankTransaction] = []

    for transaction in transactions:
        key = _transaction_key(transaction)

        if key is None:
            unique.append(transaction)
            continue

        if key in seen_keys:
            duplicates.append(transaction)
            continue

        seen_keys.add(key)
        unique.append(transaction)

    return TransactionDeduplicationResult(
        unique=tuple(unique), duplicates=tuple(duplicates)
    )
