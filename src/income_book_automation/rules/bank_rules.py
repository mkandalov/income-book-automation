"""Deterministic bank transaction classification rules."""

from income_book_automation.models import (
    BankTransaction,
    ClassifiedTransaction,
    ClientProfile,
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

    counterparty_account = _normalize_account(transaction.counterparty_account)

    client_accounts = {_normalize_account(account) for account in client.own_accounts}

    if counterparty_account and counterparty_account in client_accounts:
        return ClassifiedTransaction(
            transaction=transaction,
            category=TransactionCategory.OWN_TRANSFER,
            reason="counterparty account belongs to client",
        )

    counterparty_tax_id = _normalize_tax_id(transaction.counterparty_tax_id)
    client_tax_id = _normalize_tax_id(client.tax_id)

    if counterparty_tax_id and client_tax_id and counterparty_tax_id == client_tax_id:
        return ClassifiedTransaction(
            transaction=transaction,
            category=TransactionCategory.OWN_TRANSFER,
            reason="counterparty tax ID belongs to client",
        )

    client_names = {
        _normalize_text(name)
        for name in (client.legal_name, *client.name_aliases)
        if name.strip()
    }

    counterparty_name = _normalize_text(transaction.counterparty)

    if counterparty_name and counterparty_name in client_names:
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

    if not any(
        (
            counterparty_name,
            counterparty_account,
            counterparty_tax_id,
            payment_purpose,
        )
    ):
        return ClassifiedTransaction(
            transaction=transaction,
            category=TransactionCategory.NEEDS_REVIEW,
            reason="insufficient counterparty information",
        )

    return ClassifiedTransaction(
        transaction=transaction,
        category=TransactionCategory.INCOME,
        reason="eligible incoming payment",
    )
