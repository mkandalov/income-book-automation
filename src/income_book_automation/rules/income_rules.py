"""Income classification rules."""

from datetime import date
from decimal import Decimal

from income_book_automation.models import (
    ClassifiedTransaction,
    DailyBankIncome,
    DailyCheckboxRevenue,
    DailyIncomeBookEntry,
    TransactionCategory,
)


def aggregate_checkbox_by_date(
    records: list[DailyCheckboxRevenue],
) -> list[DailyCheckboxRevenue]:
    records_by_date: dict[date, DailyCheckboxRevenue] = {}

    for record in records:
        existing_record = records_by_date.get(record.date)

        if existing_record is None:
            records_by_date[record.date] = record.model_copy()
        else:
            existing_record.card_revenue += record.card_revenue
            existing_record.card_refund += record.card_refund
            existing_record.cash_revenue += record.cash_revenue
            existing_record.cash_refund += record.cash_refund

    return sorted(records_by_date.values(), key=lambda record: record.date)


def aggregate_bank_income_by_date(
    records: list[ClassifiedTransaction],
) -> list[DailyBankIncome]:
    totals_by_date: dict[date, Decimal] = {}

    for record in records:
        if record.category is not TransactionCategory.INCOME:
            continue

        transaction = record.transaction
        current_total = totals_by_date.get(transaction.date, Decimal("0.00"))
        totals_by_date[transaction.date] = current_total + transaction.credit

    return [
        DailyBankIncome(
            date=transaction_date,
            amount=totals_by_date[transaction_date],
        )
        for transaction_date in sorted(totals_by_date)
    ]


def merge_daily_income(
    checkbox_records: list[DailyCheckboxRevenue],
    bank_records: list[DailyBankIncome],
) -> list[DailyIncomeBookEntry]:
    """Merge already aggregated Checkbox and bank records by date."""

    checkbox_by_date = {record.date: record for record in checkbox_records}

    bank_by_date = {record.date: record for record in bank_records}

    all_dates = sorted(set(checkbox_by_date) | set(bank_by_date))

    zero = Decimal("0.00")
    result: list[DailyIncomeBookEntry] = []

    for transaction_date in all_dates:
        checkbox_record = checkbox_by_date.get(transaction_date)
        bank_record = bank_by_date.get(transaction_date)

        checkbox_card_income = (
            checkbox_record.card_net if checkbox_record is not None else zero
        )

        checkbox_cash_income = (
            checkbox_record.cash_net if checkbox_record is not None else zero
        )

        bank_income = bank_record.amount if bank_record is not None else zero

        if (
            checkbox_card_income == zero
            and checkbox_cash_income == zero
            and bank_income == zero
        ):
            continue

        result.append(
            DailyIncomeBookEntry(
                date=transaction_date,
                checkbox_card_income=checkbox_card_income,
                checkbox_cash_income=checkbox_cash_income,
                bank_income=bank_income,
            )
        )

    return result
