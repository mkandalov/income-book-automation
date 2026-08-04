from datetime import date
from decimal import Decimal

from income_book_automation.models import (
    BankName,
    BankTransaction,
    ClientProfile,
    TransactionCategory,
)
from income_book_automation.rules.bank_rules import classify_bank_transaction


def _client_profile() -> ClientProfile:
    return ClientProfile(
        client_id="client-001",
        legal_name="ФОП Тестовий Тарас Іванович",
        tax_id="1111111111",
        own_accounts={"UA000000000000000000000000001"},
        name_aliases={"Тестовий Тарас Іванович"},
    )


def _credit_transaction(**overrides: object) -> BankTransaction:
    fields: dict[str, object] = {
        "date": date(2026, 1, 15),
        "bank": BankName.PUMB,
        "account_number": "UA000000000000000000000000009",
        "currency": "UAH",
        "document_number": "TEST-001",
        "debit": Decimal("0.00"),
        "credit": Decimal("100.00"),
        "counterparty": "ТОВ Тестовий покупець",
        "counterparty_account": "UA000000000000000000000000002",
        "payment_purpose": "Оплата за тестові послуги",
        "counterparty_tax_id": "2222222222",
    }
    fields.update(overrides)
    return BankTransaction(**fields)


def test_classifies_debit_as_excluded() -> None:
    transaction = _credit_transaction(
        debit=Decimal("100.00"),
        credit=Decimal("0.00"),
    )

    result = classify_bank_transaction(transaction, _client_profile())

    assert result.category is TransactionCategory.EXCLUDED
    assert result.reason == "debit transaction"


def test_classifies_known_own_account_as_own_transfer() -> None:
    transaction = _credit_transaction(
        counterparty_account=" ua000000000000000000000000001 ",
    )

    result = classify_bank_transaction(transaction, _client_profile())

    assert result.category is TransactionCategory.OWN_TRANSFER
    assert result.reason == "counterparty account belongs to client"


def test_classifies_matching_tax_id_as_own_transfer() -> None:
    transaction = _credit_transaction(counterparty_tax_id=" 1111111111 ")

    result = classify_bank_transaction(transaction, _client_profile())

    assert result.category is TransactionCategory.OWN_TRANSFER
    assert result.reason == "counterparty tax ID belongs to client"


def test_classifies_matching_name_alias_as_own_transfer() -> None:
    transaction = _credit_transaction(
        counterparty="  ТЕСТОВИЙ   ТАРАС ІВАНОВИЧ  ",
    )

    result = classify_bank_transaction(transaction, _client_profile())

    assert result.category is TransactionCategory.OWN_TRANSFER
    assert result.reason == "counterparty name belongs to client"


def test_excludes_refund_payment_purpose() -> None:
    transaction = _credit_transaction(
        payment_purpose="ПОВЕРНЕННЯ   КОШТІВ за тестовим платежем",
    )

    result = classify_bank_transaction(transaction, _client_profile())

    assert result.category is TransactionCategory.EXCLUDED
    assert result.reason == "refund payment"


def test_excludes_returnable_financial_assistance() -> None:
    transaction = _credit_transaction(
        payment_purpose="Поворотна фінансова допомога згідно договору",
    )

    result = classify_bank_transaction(transaction, _client_profile())

    assert result.category is TransactionCategory.EXCLUDED
    assert result.reason == "returnable financial assistance"


def test_excludes_currency_sale_proceeds() -> None:
    transaction = _credit_transaction(
        payment_purpose="Надходження гривні від продажу іноземної валюти",
    )

    result = classify_bank_transaction(transaction, _client_profile())

    assert result.category is TransactionCategory.EXCLUDED
    assert result.reason == "currency sale proceeds"


def test_classifies_regular_credit_as_income() -> None:
    transaction = _credit_transaction()

    result = classify_bank_transaction(transaction, _client_profile())

    assert result.transaction is transaction
    assert result.category is TransactionCategory.INCOME
    assert result.reason == "eligible incoming payment"


def test_sends_incomplete_credit_to_manual_review() -> None:
    transaction = _credit_transaction(
        counterparty="",
        counterparty_account="",
        counterparty_tax_id=None,
        payment_purpose="",
    )

    result = classify_bank_transaction(transaction, _client_profile())

    assert result.category is TransactionCategory.NEEDS_REVIEW
    assert result.reason == "insufficient counterparty information"
