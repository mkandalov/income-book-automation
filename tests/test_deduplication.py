from datetime import date
from decimal import Decimal

from income_book_automation.models import BankName, BankTransaction
from income_book_automation.rules.deduplication import (
    deduplicate_bank_transaction,
)


def _transaction(
    *,
    bank: BankName = BankName.PUMB,
    account_number: str = "UA000000000000000000000000001",
    document_number: str = "TEST-DOC-001",
    counterparty_account: str = "UA000000000000000000000000002",
) -> BankTransaction:
    return BankTransaction(
        date=date(2026, 6, 1),
        bank=bank,
        account_number=account_number,
        currency="UAH",
        document_number=document_number,
        debit=Decimal("0.00"),
        credit=Decimal("100.00"),
        counterparty="ТОВ Тестовий платник",
        counterparty_account=counterparty_account,
        payment_purpose="Оплата за тестові послуги",
        counterparty_tax_id="11111111",
    )


def test_deduplicate_bank_transaction_separates_duplicate() -> None:
    original = _transaction()
    duplicate = original.model_copy()

    result = deduplicate_bank_transaction([original, duplicate])

    assert result.unique == (original,)
    assert result.duplicates == (duplicate,)


def test_deduplicate_bank_transaction_normalizes_identifiers() -> None:
    original = _transaction()
    duplicate = _transaction(
        account_number="ua00 0000000000000000000000001",
        document_number="  test-doc-001  ",
        counterparty_account="ua00 0000000000000000000000002",
    )

    result = deduplicate_bank_transaction([original, duplicate])

    assert result.unique == (original,)
    assert result.duplicates == (duplicate,)


def test_deduplicate_bank_transaction_keeps_different_banks() -> None:
    pumb_transaction = _transaction(bank=BankName.PUMB)
    abank_transaction = _transaction(bank=BankName.ABANK)

    result = deduplicate_bank_transaction([pumb_transaction, abank_transaction])

    assert result.unique == (pumb_transaction, abank_transaction)
    assert result.duplicates == ()


def test_deduplicate_bank_transaction_keeps_different_documents() -> None:
    first = _transaction(document_number="TEST-DOC-001")
    second = _transaction(document_number="TEST-DOC-002")

    result = deduplicate_bank_transaction([first, second])

    assert result.unique == (first, second)
    assert result.duplicates == ()


def test_deduplicate_bank_transaction_keeps_missing_document_numbers() -> None:
    first = _transaction(document_number="")
    second = first.model_copy()

    result = deduplicate_bank_transaction([first, second])

    assert result.unique == (first, second)
    assert result.duplicates == ()
