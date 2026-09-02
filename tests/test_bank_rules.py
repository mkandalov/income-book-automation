from datetime import date
from decimal import Decimal

import pytest

from income_book_automation.models import (
    BankName,
    BankTransaction,
    ClientProfile,
    ReviewField,
    TransactionCategory,
    TransactionSource,
)
from income_book_automation.rules.bank_rules import classify_bank_transaction


def _client_profile() -> ClientProfile:
    return ClientProfile(
        client_id="client-001",
        legal_name="ФОП Тестовий Тарас Іванович",
        tax_id="1111111111",
        own_accounts={"UA273000010000000000000000001"},
        name_aliases={"Тестовий Тарас Іванович"},
    )


def _credit_transaction(**overrides: object) -> BankTransaction:
    fields: dict[str, object] = {
        "source": TransactionSource(
            original_filename="synthetic-pumb.csv",
            row_number=2,
        ),
        "date": date(2026, 1, 15),
        "bank": BankName.PUMB,
        "account_number": "UA053000010000000000000000009",
        "currency": "UAH",
        "document_number": "TEST-001",
        "debit": Decimal("0.00"),
        "credit": Decimal("100.00"),
        "counterparty": "ТОВ Тестовий покупець",
        "counterparty_account": "UA973000010000000000000000002",
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
        counterparty_account=" ua273000010000000000000000001 ",
        counterparty_tax_id="1111111111",
    )

    result = classify_bank_transaction(transaction, _client_profile())

    assert result.category is TransactionCategory.OWN_TRANSFER
    assert result.reason == "counterparty account belongs to client"


def test_classifies_matching_tax_id_as_own_transfer() -> None:
    transaction = _credit_transaction(counterparty_tax_id=" 1111111111 ")

    result = classify_bank_transaction(transaction, _client_profile())

    assert result.category is TransactionCategory.OWN_TRANSFER
    assert result.reason == "counterparty tax ID belongs to client"


def test_matching_name_and_tax_id_uses_stronger_tax_id_match() -> None:
    transaction = _credit_transaction(
        counterparty="  ТЕСТОВИЙ   ТАРАС ІВАНОВИЧ  ",
        counterparty_tax_id="1111111111",
    )

    result = classify_bank_transaction(transaction, _client_profile())

    assert result.category is TransactionCategory.OWN_TRANSFER
    assert result.reason == "counterparty tax ID belongs to client"


def test_sends_known_own_account_with_foreign_tax_id_to_review() -> None:
    transaction = _credit_transaction(
        counterparty_account="UA273000010000000000000000001",
        counterparty_tax_id="2222222222",
    )

    result = classify_bank_transaction(transaction, _client_profile())

    assert result.category is TransactionCategory.NEEDS_REVIEW
    assert result.reason == "counterparty identity conflicts with client profile"
    assert result.missing_fields == frozenset()


def test_sends_matching_name_with_foreign_tax_id_to_review() -> None:
    transaction = _credit_transaction(
        counterparty="Тестовий Тарас Іванович",
        counterparty_tax_id="2222222222",
    )

    result = classify_bank_transaction(transaction, _client_profile())

    assert result.category is TransactionCategory.NEEDS_REVIEW
    assert result.reason == "counterparty identity conflicts with client profile"
    assert result.missing_fields == frozenset()


def test_unknown_account_does_not_conflict_with_matching_tax_id() -> None:
    transaction = _credit_transaction(
        counterparty_account="UA973000010000000000000000099",
        counterparty_tax_id="1111111111",
    )

    result = classify_bank_transaction(transaction, _client_profile())

    assert result.category is TransactionCategory.OWN_TRANSFER
    assert result.reason == "counterparty tax ID belongs to client"


def test_different_name_does_not_conflict_with_matching_own_identifiers() -> None:
    transaction = _credit_transaction(
        counterparty="Інший варіант назви",
        counterparty_account="UA273000010000000000000000001",
        counterparty_tax_id="1111111111",
    )

    result = classify_bank_transaction(transaction, _client_profile())

    assert result.category is TransactionCategory.OWN_TRANSFER
    assert result.reason == "counterparty account belongs to client"


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


def test_excludes_sense_acquiring_when_checkbox_is_included() -> None:
    transaction = _credit_transaction(
        bank=BankName.SENSE,
        counterparty='АТ "СЕНС БАНК"',
        counterparty_tax_id="23494714",
        payment_purpose=(
            "Зарах.еквайрінг; сума 100.00грн; комісія 1.30грн"
        ),
        credit=Decimal("98.70"),
    )

    result = classify_bank_transaction(
        transaction,
        _client_profile(),
        checkbox_included=True,
    )

    assert result.category is TransactionCategory.EXCLUDED
    assert result.reason == "Sense acquiring settlement covered by Checkbox"


@pytest.mark.parametrize(
    ("overrides", "expected_missing_field"),
    [
        ({"document_number": "   "}, ReviewField.DOCUMENT_NUMBER),
        ({"counterparty": "   "}, ReviewField.COUNTERPARTY),
        ({"counterparty_account": ""}, ReviewField.COUNTERPARTY_ACCOUNT),
        ({"counterparty_tax_id": None}, ReviewField.COUNTERPARTY_TAX_ID),
        ({"payment_purpose": "\t"}, ReviewField.PAYMENT_PURPOSE),
    ],
)
def test_sends_credit_with_each_missing_field_to_manual_review(
    overrides: dict[str, object],
    expected_missing_field: ReviewField,
) -> None:
    transaction = _credit_transaction(**overrides)

    result = classify_bank_transaction(transaction, _client_profile())

    assert result.category is TransactionCategory.NEEDS_REVIEW
    assert result.reason == "required review fields are missing"
    assert result.missing_fields == frozenset({expected_missing_field})


def test_manual_review_records_all_missing_fields() -> None:
    transaction = _credit_transaction(
        document_number="",
        counterparty="",
        counterparty_account="",
        counterparty_tax_id=None,
        payment_purpose="",
    )

    result = classify_bank_transaction(transaction, _client_profile())

    assert result.category is TransactionCategory.NEEDS_REVIEW
    assert result.missing_fields == frozenset(ReviewField)


def test_missing_fields_take_priority_for_incoming_own_transfer() -> None:
    transaction = _credit_transaction(
        counterparty_account="UA273000010000000000000000001",
        payment_purpose="",
    )

    result = classify_bank_transaction(transaction, _client_profile())

    assert result.category is TransactionCategory.NEEDS_REVIEW
    assert result.missing_fields == frozenset({ReviewField.PAYMENT_PURPOSE})


def test_missing_review_fields_do_not_block_debit_exclusion() -> None:
    transaction = _credit_transaction(
        document_number="",
        debit=Decimal("100.00"),
        credit=Decimal("0.00"),
        counterparty="",
        counterparty_account="",
        counterparty_tax_id=None,
        payment_purpose="",
    )

    result = classify_bank_transaction(transaction, _client_profile())

    assert result.category is TransactionCategory.EXCLUDED
    assert result.reason == "debit transaction"
    assert result.missing_fields == frozenset()
