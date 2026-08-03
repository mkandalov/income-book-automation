from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from income_book_automation.models import (
    BankName,
    BankTransaction,
    DailyCheckboxRevenue,
)


def _bank_transaction_fields() -> dict[str, object]:
    return {
        "date": date(2026, 1, 15),
        "bank": BankName.PUMB,
        "account_number": "UA000000000000000000000000001",
        "currency": "UAH",
        "document_number": "TEST-001",
        "debit": Decimal("0.00"),
        "credit": Decimal("10.00"),
        "counterparty": "ТОВ Тестовий клієнт",
        "counterparty_account": "UA000000000000000000000000002",
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
    assert transaction.account_number == "UA000000000000000000000000001"
    assert transaction.currency == "UAH"
    assert transaction.debit == Decimal("0.00")
    assert transaction.credit == Decimal("10.00")
    assert transaction.counterparty_account == "UA000000000000000000000000002"
    assert transaction.counterparty_tax_id == "0000000000"


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
