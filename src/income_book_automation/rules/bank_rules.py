"""Deterministic bank transaction classification rules."""

from income_book_automation.models import (
    BankTransaction,
    ClassifiedTransaction,
    ClientProfile,
    ReviewField,
    TransactionCategory,
)

EXCLUDED_PAYMENT_RULES = (
    ("повернення коштів", "refund payment"),
    ("Повернення", "refund"),
    (
        "поворотна фінансова допомога",
        "returnable financial assistance",
    ),
    (
        "поворотно фінансова допомога",
        "returnable financial assistance",
    ),
    ("гривні від продажу", "currency sale proceeds"),
)


def _normalize_account(value: str) -> str:
    return "".join(value.split()).upper()


def _normalize_tax_id(value: str | None) -> str:
    if value is None:
        return ""

    return "".join(character for character in value if character.isdigit())


def _normalize_text(value: str) -> str:
    value = value.casefold().replace("-", " ")
    return " ".join(value.split())


def _find_missing_review_fields(
    transaction: BankTransaction,
) -> frozenset[ReviewField]:
    missing_fields: set[ReviewField] = set()

    if not transaction.document_number.strip():
        missing_fields.add(ReviewField.DOCUMENT_NUMBER)

    if not _normalize_text(transaction.counterparty):
        missing_fields.add(ReviewField.COUNTERPARTY)

    if not _normalize_account(transaction.counterparty_account):
        missing_fields.add(ReviewField.COUNTERPARTY_ACCOUNT)

    if not _normalize_tax_id(transaction.counterparty_tax_id):
        missing_fields.add(ReviewField.COUNTERPARTY_TAX_ID)

    if not _normalize_text(transaction.payment_purpose):
        missing_fields.add(ReviewField.PAYMENT_PURPOSE)

    return frozenset(missing_fields)


def classify_bank_transaction(
    transaction: BankTransaction,
    client: ClientProfile,
) -> ClassifiedTransaction:
    if transaction.debit > 0:
        return ClassifiedTransaction(
            transaction=transaction,
            category=TransactionCategory.EXCLUDED,
            reason="debit transaction",
        )

    missing_fields = _find_missing_review_fields(transaction)

    if missing_fields:
        return ClassifiedTransaction(
            transaction=transaction,
            category=TransactionCategory.NEEDS_REVIEW,
            reason="required review fields are missing",
            missing_fields=missing_fields,
        )

    counterparty_account = _normalize_account(transaction.counterparty_account)
    client_accounts = {_normalize_account(account) for account in client.own_accounts}
    account_matches = counterparty_account in client_accounts

    counterparty_tax_id = _normalize_tax_id(transaction.counterparty_tax_id)
    client_tax_id = _normalize_tax_id(client.tax_id)
    tax_id_matches = counterparty_tax_id == client_tax_id

    client_names = {
        _normalize_text(name)
        for name in (client.legal_name, *client.name_aliases)
        if name.strip()
    }
    counterparty_name = _normalize_text(transaction.counterparty)
    name_matches = counterparty_name in client_names

    has_foreign_tax_id = bool(
        counterparty_tax_id and client_tax_id and not tax_id_matches
    )

    if has_foreign_tax_id and (account_matches or name_matches):
        return ClassifiedTransaction(
            transaction=transaction,
            category=TransactionCategory.NEEDS_REVIEW,
            reason="counterparty identity conflicts with client profile",
        )

    if account_matches:
        return ClassifiedTransaction(
            transaction=transaction,
            category=TransactionCategory.OWN_TRANSFER,
            reason="counterparty account belongs to client",
        )

    if tax_id_matches:
        return ClassifiedTransaction(
            transaction=transaction,
            category=TransactionCategory.OWN_TRANSFER,
            reason="counterparty tax ID belongs to client",
        )

    if name_matches:
        return ClassifiedTransaction(
            transaction=transaction,
            category=TransactionCategory.OWN_TRANSFER,
            reason="counterparty name belongs to client",
        )

    payment_purpose = _normalize_text(transaction.payment_purpose)

    for pattern, reason in EXCLUDED_PAYMENT_RULES:
        if _normalize_text(pattern) in payment_purpose:
            return ClassifiedTransaction(
                transaction=transaction,
                category=TransactionCategory.EXCLUDED,
                reason=reason,
            )

    return ClassifiedTransaction(
        transaction=transaction,
        category=TransactionCategory.INCOME,
        reason="eligible incoming payment",
    )
