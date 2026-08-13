from datetime import date
from decimal import Decimal

from income_book_automation.models import (
    BankName,
    BankTransaction,
    CheckboxPaymentMethod,
    CheckboxRefundWarning,
    ClassifiedTransaction,
    DailyBankIncome,
    DailyCheckboxRevenue,
    DailyIncomeBookEntry,
    TransactionCategory,
    TransactionSource,
)
from income_book_automation.rules.income_rules import (
    aggregate_bank_income_by_date,
    aggregate_checkbox_by_date,
    find_checkbox_refund_warnings,
    merge_daily_income,
)


def _record(
    day: int,
    *,
    card_revenue: int,
    card_refund: int,
    cash_revenue: int,
    cash_refund: int,
) -> DailyCheckboxRevenue:
    return DailyCheckboxRevenue(
        date=date(2026, 6, day),
        card_revenue=Decimal(card_revenue),
        card_refund=Decimal(card_refund),
        cash_revenue=Decimal(cash_revenue),
        cash_refund=Decimal(cash_refund),
    )


def _classified_transaction(
    day: int,
    amount: str,
    category: TransactionCategory,
) -> ClassifiedTransaction:
    transaction = BankTransaction(
        source=TransactionSource(
            original_filename="synthetic-pumb.csv",
            row_number=day + 1,
        ),
        date=date(2026, 6, day),
        bank=BankName.PUMB,
        account_number="UA273000010000000000000000001",
        currency="UAH",
        document_number=f"TEST-{day}-{amount}",
        debit=Decimal("0.00"),
        credit=Decimal(amount),
        counterparty="ТОВ Тестовий платник",
        counterparty_account="UA973000010000000000000000002",
        payment_purpose="Оплата за тестові послуги",
        counterparty_tax_id="2222222222",
    )
    return ClassifiedTransaction(
        transaction=transaction,
        category=category,
        reason="synthetic test classification",
    )


def test_aggregate_checkbox_by_date_groups_and_sorts_records() -> None:
    first_record = _record(
        1,
        card_revenue=1000,
        card_refund=100,
        cash_revenue=200,
        cash_refund=20,
    )
    records = [
        _record(
            2,
            card_revenue=2000,
            card_refund=0,
            cash_revenue=0,
            cash_refund=0,
        ),
        first_record,
        _record(
            1,
            card_revenue=500,
            card_refund=50,
            cash_revenue=300,
            cash_refund=30,
        ),
    ]

    result = aggregate_checkbox_by_date(records)

    assert [record.date for record in result] == [
        date(2026, 6, 1),
        date(2026, 6, 2),
    ]
    assert result[0].card_revenue == Decimal(1500)
    assert result[0].card_refund == Decimal(150)
    assert result[0].cash_revenue == Decimal(500)
    assert result[0].cash_refund == Decimal(50)
    assert result[0].card_net == Decimal(1350)
    assert result[0].cash_net == Decimal(450)
    assert result[0].total_net == Decimal(1800)
    assert first_record.card_revenue == Decimal(1000)


def test_aggregate_checkbox_by_date_accepts_empty_list() -> None:
    assert aggregate_checkbox_by_date([]) == []


def test_find_checkbox_refund_warnings_reports_negative_daily_results() -> None:
    raw_records = [
        _record(
            1,
            card_revenue=100,
            card_refund=150,
            cash_revenue=20,
            cash_refund=0,
        ),
        _record(
            1,
            card_revenue=50,
            card_refund=30,
            cash_revenue=0,
            cash_refund=25,
        ),
        _record(
            2,
            card_revenue=100,
            card_refund=100,
            cash_revenue=50,
            cash_refund=40,
        ),
    ]
    daily_records = aggregate_checkbox_by_date(raw_records)

    result = find_checkbox_refund_warnings(daily_records)

    assert result == [
        CheckboxRefundWarning(
            date=date(2026, 6, 1),
            payment_method=CheckboxPaymentMethod.CARD,
            revenue=Decimal(150),
            refund=Decimal(180),
        ),
        CheckboxRefundWarning(
            date=date(2026, 6, 1),
            payment_method=CheckboxPaymentMethod.CASH,
            revenue=Decimal(20),
            refund=Decimal(25),
        ),
    ]
    assert result[0].result == Decimal(-30)
    assert result[1].result == Decimal(-5)


def test_find_checkbox_refund_warnings_accepts_empty_and_zero_results() -> None:
    zero_result = _record(
        1,
        card_revenue=100,
        card_refund=100,
        cash_revenue=50,
        cash_refund=50,
    )

    assert find_checkbox_refund_warnings([]) == []
    assert find_checkbox_refund_warnings([zero_result]) == []


def test_aggregate_bank_income_by_date_groups_sorts_and_filters() -> None:
    last_income_record = _classified_transaction(
        1,
        "5.00",
        TransactionCategory.INCOME,
    )
    ignored_record = _classified_transaction(
        3,
        "99.00",
        TransactionCategory.EXCLUDED,
    )
    records = [
        _classified_transaction(2, "20.00", TransactionCategory.INCOME),
        _classified_transaction(1, "10.00", TransactionCategory.INCOME),
        last_income_record,
        _classified_transaction(1, "99.00", TransactionCategory.OWN_TRANSFER),
        _classified_transaction(2, "99.00", TransactionCategory.EXCLUDED),
        _classified_transaction(2, "99.00", TransactionCategory.NEEDS_REVIEW),
        ignored_record,
    ]

    result = aggregate_bank_income_by_date(records)

    assert result == [
        DailyBankIncome(date=date(2026, 6, 1), amount=Decimal("15.00")),
        DailyBankIncome(date=date(2026, 6, 2), amount=Decimal("20.00")),
    ]
    assert last_income_record.transaction.date == date(2026, 6, 1)
    assert ignored_record.transaction.date == date(2026, 6, 3)


def test_aggregate_bank_income_by_date_accepts_empty_list() -> None:
    assert aggregate_bank_income_by_date([]) == []


def test_merge_daily_income_uses_all_dates_and_omits_zero_rows() -> None:
    checkbox_records = [
        _record(
            1,
            card_revenue=0,
            card_refund=0,
            cash_revenue=0,
            cash_refund=0,
        ),
        _record(
            2,
            card_revenue=100,
            card_refund=10,
            cash_revenue=50,
            cash_refund=0,
        ),
        _record(
            3,
            card_revenue=0,
            card_refund=0,
            cash_revenue=25,
            cash_refund=0,
        ),
    ]
    bank_records = [
        DailyBankIncome(date=date(2026, 6, 2), amount=Decimal("20.00")),
        DailyBankIncome(date=date(2026, 6, 4), amount=Decimal("30.00")),
    ]

    result = merge_daily_income(checkbox_records, bank_records)

    assert result == [
        DailyIncomeBookEntry(
            date=date(2026, 6, 2),
            checkbox_card_income=Decimal("90.00"),
            checkbox_cash_income=Decimal("50.00"),
            bank_income=Decimal("20.00"),
        ),
        DailyIncomeBookEntry(
            date=date(2026, 6, 3),
            checkbox_card_income=Decimal("0.00"),
            checkbox_cash_income=Decimal("25.00"),
            bank_income=Decimal("0.00"),
        ),
        DailyIncomeBookEntry(
            date=date(2026, 6, 4),
            checkbox_card_income=Decimal("0.00"),
            checkbox_cash_income=Decimal("0.00"),
            bank_income=Decimal("30.00"),
        ),
    ]
    assert result[0].total_income == Decimal("160.00")


def test_merge_daily_income_accepts_empty_sources() -> None:
    assert merge_daily_income([], []) == []
