from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from income_book_automation.models import (
    BankName,
    BankTransaction,
    ClassifiedTransaction,
    ClientProfile,
    DailyCheckboxRevenue,
    ReviewField,
    TransactionCategory,
    TransactionSource,
)


def _bank_transaction_fields() -> dict[str, object]:
    return {
        "source": TransactionSource(
            original_filename="synthetic-pumb.csv",
            row_number=2,
        ),
        "date": date(2026, 1, 15),
        "bank": BankName.PUMB,
        "account_number": "UA273000010000000000000000001",
        "currency": "UAH",
        "document_number": "TEST-001",
        "debit": Decimal("0.00"),
        "credit": Decimal("10.00"),
        "counterparty": "ТОВ Тестовий клієнт",
        "counterparty_account": "UA973000010000000000000000002",
        "payment_purpose": "Оплата за тестові послуги",
        "counterparty_tax_id": "0000000000",
    }


def test_calculates_daily_net_revenue() -> None:
    record = DailyCheckboxRevenue(
        date=date(2026, 6, 18),
        card_revenue=Decimal("37331.00"),
        card_refund=Decimal("844.00"),
        cash_revenue=Decimal("0.00"),
        cash_refund=Decimal("0.00"),
    )

    assert record.card_net == Decimal("36487.00")
    assert record.cash_net == Decimal("0.00")
    assert record.total_net == Decimal("36487.00")


def test_bank_transaction_accepts_credit() -> None:
    transaction = BankTransaction(**_bank_transaction_fields())

    assert transaction.bank is BankName.PUMB
    assert transaction.account_number == "UA273000010000000000000000001"
    assert transaction.currency == "UAH"
    assert transaction.debit == Decimal("0.00")
    assert transaction.credit == Decimal("10.00")
    assert transaction.counterparty_account == "UA973000010000000000000000002"
    assert transaction.counterparty_tax_id == "0000000000"
    assert transaction.source.original_filename == "synthetic-pumb.csv"
    assert transaction.source.row_number == 2


def test_transaction_source_normalizes_filename() -> None:
    source = TransactionSource(
        original_filename="  synthetic-pumb.csv  ",
        row_number=7,
    )

    assert source.original_filename == "synthetic-pumb.csv"
    assert source.row_number == 7


@pytest.mark.parametrize("filename", ["", "   "])
def test_transaction_source_rejects_blank_filename(filename: str) -> None:
    with pytest.raises(
        ValidationError,
        match="original filename must not be blank",
    ):
        TransactionSource(
            original_filename=filename,
            row_number=2,
        )


@pytest.mark.parametrize("row_number", [0, -1])
def test_transaction_source_rejects_invalid_row_number(row_number: int) -> None:
    with pytest.raises(ValidationError):
        TransactionSource(
            original_filename="synthetic-pumb.csv",
            row_number=row_number,
        )


def test_bank_transaction_requires_source() -> None:
    fields = _bank_transaction_fields()
    del fields["source"]

    with pytest.raises(ValidationError, match="source"):
        BankTransaction(**fields)


def test_bank_transaction_rejects_two_positive_sides() -> None:
    fields = _bank_transaction_fields()
    fields["debit"] = Decimal("5.00")

    with pytest.raises(
        ValidationError,
        match="exactly one of debit or credit must be positive",
    ):
        BankTransaction(**fields)


def test_bank_transaction_rejects_zero_sides() -> None:
    fields = _bank_transaction_fields()
    fields["credit"] = Decimal("0.00")

    with pytest.raises(
        ValidationError,
        match="exactly one of debit or credit must be positive",
    ):
        BankTransaction(**fields)


def test_bank_transaction_allows_missing_counterparty_tax_id() -> None:
    fields = _bank_transaction_fields()
    fields["counterparty_tax_id"] = None

    transaction = BankTransaction(**fields)

    assert transaction.counterparty_tax_id is None


def test_bank_transaction_normalizes_iban_values() -> None:
    fields = _bank_transaction_fields()
    fields["account_number"] = " ua27 3000010000000000000000001 "
    fields["counterparty_account"] = " ua97 3000010000000000000000002 "

    transaction = BankTransaction(**fields)

    assert transaction.account_number == "UA273000010000000000000000001"
    assert transaction.counterparty_account == "UA973000010000000000000000002"


@pytest.mark.parametrize("field_name", ["account_number", "counterparty_account"])
def test_bank_transaction_rejects_invalid_iban(field_name: str) -> None:
    fields = _bank_transaction_fields()
    fields[field_name] = "UA003000010000000000000000001"

    with pytest.raises(ValidationError, match="checksum"):
        BankTransaction(**fields)


def test_bank_transaction_accepts_non_iban_counterparty_account() -> None:
    fields = _bank_transaction_fields()
    fields["counterparty_account"] = " 2600 1234567890 "

    transaction = BankTransaction(**fields)

    assert transaction.counterparty_account == "26001234567890"


def test_client_profile_stores_identity_and_own_accounts() -> None:
    profile = ClientProfile(
        client_id="client-001",
        legal_name="ФОП Тестовий Тарас Іванович",
        tax_id="1111111111",
        own_accounts={
            "UA273000010000000000000000001",
            "UA973000010000000000000000002",
        },
        name_aliases={"Тестовий Тарас Іванович"},
    )

    assert profile.client_id == "client-001"
    assert len(profile.own_accounts) == 2
    assert isinstance(profile.own_accounts, frozenset)
    assert profile.name_aliases == frozenset({"Тестовий Тарас Іванович"})


def test_client_profile_uses_empty_own_accounts_by_default() -> None:
    profile = ClientProfile(
        client_id="client-001",
        legal_name="ФОП Тестовий Тарас Іванович",
        tax_id="1111111111",
    )

    assert profile.own_accounts == frozenset()


def test_client_profile_rejects_invalid_own_account() -> None:
    with pytest.raises(ValidationError, match="checksum"):
        ClientProfile(
            client_id="client-001",
            legal_name="ФОП Тестовий Тарас Іванович",
            tax_id="1111111111",
            own_accounts={"UA003000010000000000000000001"},
        )


def test_classified_transaction_records_category_and_reason() -> None:
    transaction = BankTransaction(**_bank_transaction_fields())

    result = ClassifiedTransaction(
        transaction=transaction,
        category=TransactionCategory.INCOME,
        reason="eligible incoming payment",
    )

    assert result.transaction is transaction
    assert result.category is TransactionCategory.INCOME
    assert result.reason == "eligible incoming payment"
    assert result.missing_fields == frozenset()


def test_classified_transaction_stores_missing_review_fields() -> None:
    transaction = BankTransaction(**_bank_transaction_fields())

    result = ClassifiedTransaction(
        transaction=transaction,
        category=TransactionCategory.NEEDS_REVIEW,
        reason="missing required classification fields",
        missing_fields={
            ReviewField.COUNTERPARTY_ACCOUNT,
            ReviewField.COUNTERPARTY_TAX_ID,
        },
    )

    assert result.missing_fields == frozenset(
        {
            ReviewField.COUNTERPARTY_ACCOUNT,
            ReviewField.COUNTERPARTY_TAX_ID,
        }
    )
    assert isinstance(result.missing_fields, frozenset)
